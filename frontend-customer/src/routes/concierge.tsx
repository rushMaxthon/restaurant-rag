import { useEffect, useRef, useState } from "react";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StorefrontHero } from "@/components/bangkok/storefront-hero";
import { WaiterPrompt } from "@/components/bangkok/waiter-prompt";
import {
  ApiError,
  getChatHistory,
  placeOrderFromChat,
  getToken,
  streamChatMessage,
  type CartAction,
  type ChatStreamDone,
  type ChatSuggestion,
} from "@/lib/api";
import { type MenuItem} from "@/lib/bangkok-data";
import { clearChatSession, readChatSession, storeChatSession } from "@/lib/chat-session";
import { guestPreferencesForRequest, mergeGuestPreferences } from "@/lib/guest-preferences";
import { cartLinesForRequest } from "@/lib/suggestions";
import { hasCapability, useBangkokStore } from "@/lib/bangkok-store";
import { queryKeys, useMenuItems } from "@/lib/queries";
import { useAuth } from "@/lib/auth";
import { pageMeta, useStorefrontCopy, useMoney } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

type ConciergeSearch = { q?: string };

/**
 * "Added Margherita Pizza ×1 to your cart." — from the action and the loaded
 * menu, never from anything the server said, so the line cannot name a price
 * or a dish the menu page would disagree with.
 */
function describeAppliedActions(actions: CartAction[], menu: MenuItem[]): string | undefined {
  const nameOf = (id: string | null) => menu.find((item) => item.id === id)?.name ?? "that dish";
  const lines = actions
    .filter((action) => action.status === "applied")
    .map((action) => {
      const qty = action.quantity ?? 1;
      switch (action.kind) {
        case "add":
          return `Added ${nameOf(action.menu_item_id)} ×${qty} to your cart.`;
        case "remove":
          return `Removed ${nameOf(action.menu_item_id)} from your cart.`;
        case "set_quantity":
          return `${nameOf(action.menu_item_id)} is now ×${qty}.`;
        case "clear":
          return "Cleared your cart.";
        default:
          return undefined;
      }
    })
    .filter((line): line is string => Boolean(line));
  if (!lines.length) return undefined;
  const added = actions.some((action) => action.status === "applied" && action.kind === "add");
  return lines.join(" ") + (added ? " Add more, or check out?" : "");
}

export const Route = createFileRoute("/concierge")({
  validateSearch: (search: Record<string, unknown>): ConciergeSearch =>
    typeof search["q"] === "string" ? { q: search["q"] as string } : {},
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Food concierge", "Ask about the menu and get help choosing what to order."),
  }),
  component: ConciergePage,
});


const STARTERS = [
  "Something spicy and vegetarian",
  "A light lunch under $15",
  "Comfort food for a rainy day",
];

type Status = "idle" | "waiting" | "streaming" | "done" | "error";

/**
 * One side of one exchange.
 *
 * Suggestions hang off the assistant turn that produced them rather than off
 * the page, which is the whole reason this replaced a single `reply` string:
 * asking a second question used to overwrite the dishes from the first, so the
 * cards on screen could belong to a question no longer visible anywhere.
 */
/** One cart-action proposal, plus whether the customer has already acted on it. */
type ProposalState = {
  action: CartAction;
  resolution: "pending" | "confirmed" | "dismissed";
};

type Turn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  suggestions: ChatSuggestion[];
  /** The server's own id for this turn — required to confirm a proposal on it. */
  turnId?: string | undefined;
  proposals?: ProposalState[] | undefined;
  /** Whether anything referenced by this turn wasn't on this branch's menu. */
  hadDropped?: boolean;
  /** Whether an applied change (auto or confirmed) has touched the cart. */
  cartUpdated?: boolean;
  /** The order this turn placed, with the link to pay it. */
  placedOrder?: ChatStreamDone["placed_order"];
  /** Everything an order needs is gathered; only a confirmation is left. */
  orderReady?: boolean;
};

let turnSeq = 0;
function nextTurnId(prefix: string): string {
  turnSeq += 1;
  return `${prefix}-${turnSeq}`;
}

/**
 * Strip the markdown the model insists on emitting.
 *
 * Qwen bolds dish names with ** whether or not the prompt asks it to, and this
 * surface renders the reply as plain text — so the visitor reads
 * "the **Paneer Chilli Momos** from Momo Mountain", asterisks and all. Dropping
 * the markers beats pulling in a markdown renderer for one paragraph of prose,
 * and beats fighting the model in the prompt, which we already tried.
 */
function stripMarkdown(text: string): string {
  return text
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/(^|\s)\*(\S(?:.*?\S)?)\*(?=\s|[.,!?]|$)/g, "$1$2")
    .replace(/`([^`]+)`/g, "$1");
}

function ConciergePage() {
  // Prices in whatever this restaurant charges in.
  const money = useMoney();
  // This restaurant's own words, resolved by the root route from the
  // address the page was opened on.
  const copy = useStorefrontCopy();
  const navigate = useNavigate();
  const search = Route.useSearch();
  const store = useBangkokStore();
  const queryClient = useQueryClient();
  const { isAuthenticated } = useAuth();

  // The same branch menu the menu page renders from — LOADED here, not just
  // read from the cache. It used to be cache-only, on the reasoning that an
  // id absent from the loaded menu should be dropped; but that conflated
  // "this dish is not on the branch" with "nobody has opened the menu page
  // yet". Landing straight on /concierge and asking for a real dish meant a
  // correct add action was thrown away and the customer told the dish was
  // not on the menu. Same query key as the menu page, so this is a cache hit
  // whenever they have browsed, and one cheap fetch when they have not.
  const menuQuery = useMenuItems(store.restaurantId, store.currentLocation?.id);
  const resolveMenu = () =>
    menuQuery.data ??
    queryClient.getQueryData<MenuItem[]>(
      queryKeys.menuItems(store.restaurantId ?? "", store.currentLocation?.id),
    ) ??
    [];

  const [status, setStatus] = useState<Status>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [placing, setPlacing] = useState(false);

  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  /** Tokens as they arrive, shown only once `done` says whose answer they are. */
  const streamedRef = useRef("");
  const autoSentRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // Replay the conversation the backend kept, across sessions.
  //
  // Three things were wrong here and each on its own hid the history:
  //
  //   - it returned early when localStorage held no session id, so a customer
  //     signing in on a fresh browser saw nothing while the server held
  //     everything
  //   - it asked for ONE session, so conversations from earlier visits were
  //     invisible even when that session id was present
  //   - it ran once on mount, so logging in while the page was open loaded
  //     nothing until a reload
  //
  // The common path made all three bite at once: chat as a guest, then sign in.
  // The stored session belonged to the GUEST — whose turns are never written,
  // since `chat_history.user_id` is NOT NULL — so it fetched a session with no
  // rows and rendered an empty thread.
  useEffect(() => {
    if (!isAuthenticated) return;

    let cancelled = false;
    void (async () => {
      try {
        // No session filter: "my history" spans visits, not one tab.
        const history = await getChatHistory();
        if (cancelled || history.length === 0) return;

        // Continue the conversation the last turn belonged to, so a follow-up
        // lands in the thread it is answering rather than starting a new one.
        const latest = history[history.length - 1];
        if (latest?.session_id) {
          sessionIdRef.current = latest.session_id;
          storeChatSession(latest.session_id);
        }

        // Suggestions are not persisted with a turn, so replayed assistant
        // turns carry prose only. Re-running retrieval to rebuild those cards
        // would be a second answer to a question already answered, and would
        // spend a model call per turn to redraw history.
        setTurns(
          history.map((item) => ({
            id: item.id,
            role: item.role === "USER" ? "user" : "assistant",
            text: item.message,
            suggestions: [],
          })),
        );
        setStatus("done");
      } catch {
        // A failed replay is an empty thread, never a blocked chat.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  // A craving chip on the home screen deep-links here with ?q=... — send it
  // immediately rather than just dropping it in the box, then drop the param
  // so a back-navigation or refresh doesn't resend it.
  useEffect(() => {
    if (!search.q || autoSentRef.current) return;
    autoSentRef.current = true;
    const message = search.q;
    navigate({ to: "/concierge", search: {}, replace: true });
    void sendQuery(message);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.q]);

  useEffect(() => () => abortRef.current?.abort(), []);

  // Follow the newest turn, the way every chat surface does.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function sendQuery(message: string) {
    const text = message.trim();
    if (!text || status === "waiting" || status === "streaming") return;

    abortRef.current?.abort();
    streamedRef.current = "";
    const controller = new AbortController();
    abortRef.current = controller;

    setError(null);
    setStatus("waiting");
    setDraft("");

    // Both turns go in up front so the question stays on screen while the
    // answer is still arriving, and the answer streams into a bubble that is
    // already in place rather than appearing all at once at the end.
    const answerId = nextTurnId("a");
    setTurns((prev) => [
      ...prev,
      { id: nextTurnId("q"), role: "user", text, suggestions: [] },
      { id: answerId, role: "assistant", text: "", suggestions: [] },
    ]);

    const patchAnswer = (patch: (turn: Turn) => Turn) =>
      setTurns((prev) => prev.map((turn) => (turn.id === answerId ? patch(turn) : turn)));

    try {
      await streamChatMessage(
        {
          message: text,
          session_id: sessionIdRef.current,
          // The branch the customer chose. Without it the concierge answers
          // across every restaurant in the marketplace — it recommended Penne
          // Arrabbiata to someone asking for Thai noodles — and can suggest a
          // dish this kitchen does not make. The backend has filtered on this
          // all along; nothing was sending it.
          restaurant_id: store.restaurantId,
          restaurant_location_id: store.currentLocation?.id,
          // Undefined for a signed-in customer and for a guest who has said
          // nothing yet. The backend ignores it outright for an account, so
          // sending it would be harmless — but not sending what cannot be used
          // keeps the request honest about who it is for.
          guest_preferences: getToken() ? undefined : guestPreferencesForRequest(),
          // Identifiers only — see `cartLinesForRequest`. Lets the ordering
          // agent resolve "make it two" or "remove that" against what is
          // actually in the cart right now.
          cart: cartLinesForRequest(store.cart),
          // The line the customer is replying to, if they are replying.
          previous_reply: turns[turns.length - 1]?.text,
          recent_history: turns
            .slice(-8)
            .filter((t) => t.text.trim().length > 0)
            .map((t) => ({
              role: t.role === "user" ? ("customer" as const) : ("assistant" as const),
              text: t.text.trim().slice(0, 600),
            })),
        },
        {
          onMeta: (meta) => {
            sessionIdRef.current = meta.session_id;
            storeChatSession(meta.session_id);
            // Only ever non-empty for a guest; see ChatStreamMeta.
            mergeGuestPreferences(meta.inferred_preferences);
            patchAnswer((turn) => ({ ...turn, suggestions: meta.suggestions }));
            setStatus((s) => (s === "waiting" ? "streaming" : s));
          },
          onToken: (chunk) => {
            // Held, not shown. Two layers answer a turn and which one speaks
            // is only known at `done` — so painting these tokens meant the
            // customer watched the menu pipeline's answer type itself out and
            // then get replaced by the agent's. One answer, once.
            streamedRef.current += chunk;
          },
          onDone: (done) => {
            sessionIdRef.current = done.session_id;
            storeChatSession(done.session_id);

            // Absent entirely unless the server's ordering-agent flag is on
            // (see `ChatStreamDone`) — everything below is a no-op under the
            // old contract.
            let cartUpdated = false;
            let hadDropped = false;
            let proposals: ProposalState[] = [];
            if (done.turn_id && done.cart_actions) {
              const menu = resolveMenu();
              const { dropped, proposals: pending } = store.applyCartActions(
                done.turn_id,
                done.cart_actions,
                menu,
              );
              // Only a menu we actually hold can tell us a dish is missing
              // from it. With an empty menu the drop is ours, not the
              // branch's, and saying otherwise would be a lie.
              hadDropped = dropped.length > 0 && menu.length > 0;
              proposals = pending.map((action) => ({ action, resolution: "pending" as const }));
              // Applied and not reported back as dropped or still pending
              // means it actually changed the cart.
              cartUpdated = done.cart_actions.some(
                (action) =>
                  action.status === "applied" &&
                  !dropped.includes(action) &&
                  !pending.includes(action),
              );
            }

            // What the agent has to say, in its own words when it has them,
            // otherwise a plain statement of what it did — named from the
            // menu this page already holds, since no name crosses the wire.
            const agentLine =
              done.agent_reply?.trim() ||
              (cartUpdated && done.cart_actions
                ? describeAppliedActions(done.cart_actions, resolveMenu())
                : undefined);

            // A turn that changed the cart, or is asking to, is answered by
            // the agent. The pipeline's reply for "add one more Margherita"
            // was a paragraph about past-order suggestions — true of nothing
            // the customer asked — so on those turns the agent's line is the
            // answer and the paragraph is not shown. Every other turn keeps
            // today's reply, with the agent's line beneath it if there is one.
            // An order carries the cart away with it: those items are on the
            // order now, and leaving them behind is how someone orders twice.
            const placed = done.placed_order ?? null;
            if (placed?.order_id) store.clearCart();

            const actedOnCart = cartUpdated || proposals.length > 0;
            // Beneath the reply only when the agent has something the reply
            // does not - a question to answer, a dish refused for the diet.
            // On a plain menu question the reply already answered it, and a
            // second answer under it read as two voices (reported live).
            const agentHasMore = Boolean(done.agent_asks);

            patchAnswer((turn) => ({
              ...turn,
              text:
                (actedOnCart || agentHasMore) && agentLine
                  ? agentLine
                  : done.reply || streamedRef.current,
              suggestions: done.suggestions,
              turnId: done.turn_id,
              proposals,
              hadDropped,
              cartUpdated,
              placedOrder: placed,
              orderReady: Boolean(done.order_ready),
            }));
            setStatus("done");
          },
        },
        controller.signal,
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      // Drop the empty answer bubble; the question stays so it can be retried.
      setTurns((prev) => prev.filter((turn) => turn.id !== answerId));
      setError(
        err instanceof ApiError
          ? err.message
          : "The concierge is unavailable right now. Please try again.",
      );
      setStatus("error");
    }
  }

  function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    void sendQuery(draft);
  }

  /**
   * The customer explicitly agreeing to one proposed edit. The client forces
   * `status: "applied"` only on this one action — every other proposal on the
   * turn stays untouched until it gets its own tap.
   */
  function confirmProposal(turn: Turn, index: number) {
    if (!turn.turnId) return;
    const proposal = turn.proposals?.[index];
    if (!proposal || proposal.resolution !== "pending") return;

    if (proposal.action.kind === "checkout") {
      // The hand-off: nothing to apply, the checkout page does the rest.
      setTurns((prev) =>
        prev.map((t) =>
          t.id !== turn.id
            ? t
            : { ...t, proposals: t.proposals?.map((p, i) => (i === index ? { ...p, resolution: "confirmed" } : p)) },
        ),
      );
      void navigate({ to: "/checkout" });
      return;
    }

    const menu = resolveMenu();
    const { dropped } = store.applyCartActions(
      `${turn.turnId}:confirm:${index}`,
      [{ ...proposal.action, status: "applied" }],
      menu,
    );
    const applied = dropped.length === 0;

    setTurns((prev) =>
      prev.map((t) =>
        t.id !== turn.id
          ? t
          : {
              ...t,
              proposals: t.proposals?.map((p, i) =>
                i === index ? { ...p, resolution: applied ? "confirmed" : "dismissed" } : p,
              ),
              hadDropped: t.hadDropped || !applied,
              cartUpdated: t.cartUpdated || applied,
            },
      ),
    );
  }

  function dismissProposal(turn: Turn, index: number) {
    setTurns((prev) =>
      prev.map((t) =>
        t.id !== turn.id
          ? t
          : {
              ...t,
              proposals: t.proposals?.map((p, i) =>
                i === index ? { ...p, resolution: "dismissed" as const } : p,
              ),
            },
      ),
    );
  }

  function undoTurn(turn: Turn) {
    if (!store.undoLastChatTurn()) return;
    setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, cartUpdated: false } : t)));
  }

  /** "the Pad Thai", "your whole cart" for clear — the only two shapes a card names. */
  function proposalDishLabel(action: CartAction, menu: MenuItem[]): string {
    if (action.kind === "clear") return "your whole cart";
    return menu.find((item) => item.id === action.menu_item_id)?.name ?? "this item";
  }

  /** One line naming what the card is asking, or what it already did. */
  /**
   * Place the order, from the details this conversation already gathered.
   *
   * Deliberately not routed through the model: with `place_order` as its
   * only tool and the state spelled out, it answered "ready to be placed,
   * proceed to checkout" and placed nothing, every time. The server runs
   * the same handler either way.
   */
  async function placeOrder(turn: Turn) {
    const sessionId = sessionIdRef.current;
    if (!sessionId || !store.restaurantId || !store.currentLocation?.id || placing) return;
    setPlacing(true);
    try {
      const result = await placeOrderFromChat({
        restaurant_id: store.restaurantId,
        restaurant_location_id: store.currentLocation.id,
        session_id: sessionId,
        cart: cartLinesForRequest(store.cart),
      });
      if (result.outcome === "placed" && result.order_id) {
        store.clearCart();
        setTurns((prev) =>
          prev.map((t) =>
            t.id !== turn.id
              ? t
              : {
                  ...t,
                  orderReady: false,
                  placedOrder: {
                    order_id: result.order_id,
                    total: result.total,
                    currency: result.currency,
                    payment_url: result.payment_url,
                  },
                },
          ),
        );
      } else {
        // Refused for a reason the customer can act on: a closed branch, a
        // minimum not met, a detail still missing.
        setError(result.reason || "That order could not be placed just yet.");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That order could not be placed just yet.");
    } finally {
      setPlacing(false);
    }
  }

  function proposalCopy(action: CartAction, menu: MenuItem[], confirmed: boolean): string {
    const dish = proposalDishLabel(action, menu);
    if (action.kind === "checkout") return confirmed ? "Taking you to checkout." : "Ready to check out?";
    if (action.kind === "clear") return confirmed ? "Cleared your whole cart." : "Clear your whole cart?";
    if (action.kind === "remove") return confirmed ? `Removed ${dish}.` : `Remove ${dish}?`;
    if (action.kind === "set_quantity")
      return confirmed ? `Updated ${dish}.` : `Update the quantity of ${dish}?`;
    return confirmed ? `Added ${dish}.` : `Add ${dish}?`;
  }

  /**
   * "Ask something else" — now genuinely a new conversation.
   *
   * It used to just set status back to "idle", which worked when the page held
   * one reply. With a thread, `hasResult` is also true whenever `turns` is
   * non-empty, so that alone would leave the old conversation on screen and the
   * button looking broken.
   *
   * The stored session id goes too. Clearing the thread but keeping the session
   * would put the same turns back on the next reload, which reads as the reset
   * having silently failed. Nothing is deleted server-side — `chat_history`
   * keeps the old session, it is simply no longer the one being continued.
   */
  function startNewConversation() {
    abortRef.current?.abort();
    sessionIdRef.current = null;
    clearChatSession();
    setTurns([]);
    setError(null);
    setDraft("");
    setStatus("idle");
  }

  const hasResult = turns.length > 0 || status !== "idle";
  const busy = status === "waiting" || status === "streaming";
  const lastSuggestions =
    [...turns].reverse().find((t) => t.suggestions.length > 0)?.suggestions ?? [];

  // Hiding the nav entry is not the same as closing the door: this address is
  // bookmarkable, linkable and guessable. A restaurant that has switched Ask
  // AI off has switched it off.
  //
  // Below every hook rather than at the top of the component, because an early
  // return above them would change how many hooks run between renders — React
  // requires the count to be stable, and "it worked when I tried it" is how
  // that bug hides until the capability is actually toggled.
  if (!hasCapability(store.capabilities, "ask_ai")) {
    return (
      <div className="page-pad flex min-h-[60svh] flex-col items-center justify-center text-center">
        <h1 className="font-display text-3xl font-extrabold">Not available here</h1>
        <p className="mt-3 max-w-md text-muted">
          {copy.name} does not offer the food concierge. Browse the menu and order as
          usual.
        </p>
        <Button className="mt-6" asChild>
          <Link to="/menu">See the menu</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="pb-32">
      {!hasResult ? (
        <>
          <StorefrontHero className="min-h-[38svh]">
            <div className="hero-overlay absolute inset-0" />
            <div className="hero-copy page-pad relative flex min-h-[38svh] max-w-3xl flex-col justify-end pb-10 pt-24 text-primary-foreground">
              <Sparkles className="mb-4 size-10" />
              <h1 className="font-display text-5xl font-extrabold leading-[.98] sm:text-6xl">
                Ask the food concierge
              </h1>
              <p className="mt-4 max-w-xl text-lg font-medium">
                {copy.concierge_intro}
              </p>
            </div>
          </StorefrontHero>
          <div className="page-pad mx-auto max-w-5xl py-10">
            <div className="mb-8 flex flex-wrap gap-2">
              {STARTERS.map((s, i) => (
                <button
                  key={s}
                  onClick={() => sendQuery(s)}
                  className="category-pill rise-in"
                  style={{ "--i": i } as React.CSSProperties}
                >
                  {s}
                </button>
              ))}
            </div>
            <div
              className="concierge-welcome elevated-panel rise-in p-5"
              style={{ "--i": 3 } as React.CSSProperties}
            >
              <span className="brand-mark shrink-0">BB</span>
              <p className="pt-2 text-lg leading-relaxed">
                Tell me your mood—spicy, comforting, light—and I'll point you to a bowl.
              </p>
            </div>
          </div>
        </>
      ) : (
        <div className="page-pad mx-auto max-w-5xl py-10">
          <button onClick={startNewConversation} className="back-link mb-4">
            <ArrowLeft className="size-4" /> Ask something else
          </button>

          <div className="mb-8 flex flex-col gap-8">
            {turns.map((turn, index) => {

              if (turn.role === "user") {
                return (
                  <div key={turn.id} className="flex justify-end">
                    <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-primary px-4 py-3 text-lg font-semibold text-primary-foreground sm:max-w-[70%]">
                      {turn.text}
                    </p>
                  </div>
                );
              }

              return (
                <div key={turn.id} className="flex flex-col gap-4">
                  <div className="flex items-start gap-3">
                    <span className="brand-mark mt-1 shrink-0">BB</span>
                    <div className="max-w-3xl pt-1 text-lg text-muted">
                      {turn.text ? (
                        <p className="concierge-reply" aria-live="polite">
                          {stripMarkdown(turn.text)}
                        </p>
                      ) : (
                        <p className="typing text-lg" role="status">
                          <span className="typing-dots" aria-hidden="true">
                            <i />
                            <i />
                            <i />
                          </span>
                          Finding dishes for you…
                        </p>
                      )}
                    </div>
                  </div>

                  {/* The dish grid that used to sit here is gone: the agent now
                      recommends AND adds, so a second set of recommendations
                      beside its reply asked the customer which of the two to
                      believe. `suggestions` still arrives on the frame and is
                      still kept on the turn — restoring the grid is this block
                      again, nothing else. */}

                  {turn.proposals && turn.proposals.length > 0 && (
                    <div className="flex flex-col gap-2">
                      {turn.proposals.map((p, i) =>
                        p.resolution === "dismissed" ? null : (
                          <div
                            key={i}
                            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 py-3"
                          >
                            <span className="text-base">
                              {proposalCopy(p.action, resolveMenu(), p.resolution === "confirmed")}
                            </span>
                            {p.resolution === "pending" && (
                              <div className="flex gap-2">
                                <Button size="sm" onClick={() => confirmProposal(turn, i)}>
                                  Confirm
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => dismissProposal(turn, i)}
                                >
                                  Not now
                                </Button>
                              </div>
                            )}
                          </div>
                        ),
                      )}
                    </div>
                  )}

                  {turn.orderReady && !turn.placedOrder && (
                    <Button
                      className="w-fit"
                      disabled={placing}
                      onClick={() => placeOrder(turn)}
                    >
                      {placing ? "Placing…" : "Place order"}
                    </Button>
                  )}

                  {turn.placedOrder?.payment_url && (
                    <a
                      href={turn.placedOrder.payment_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex w-fit items-center gap-2 rounded-xl bg-primary px-4 py-3 text-base font-semibold text-primary-foreground"
                    >
                      Pay
                      {turn.placedOrder.total ? ` ${money(turn.placedOrder.total)}` : ""}
                    </a>
                  )}

                  {turn.cartUpdated && (
                    <p className="text-base text-muted-foreground">
                      Cart updated —{" "}
                      <Link to="/checkout" className="underline underline-offset-2">
                        Go to checkout
                      </Link>
                      {" · "}
                      <button
                        type="button"
                        onClick={() => undoTurn(turn)}
                        className="underline underline-offset-2"
                      >
                        Undo
                      </button>
                    </p>
                  )}

                  {turn.hadDropped && (
                    <p className="text-base text-muted-foreground">
                      Some items aren't on this branch's menu, so I left them out.
                    </p>
                  )}
                </div>
              );
            })}
          </div>

          {error && (
            <div className="inline-error form-error mt-4" role="alert">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {lastSuggestions.length > 0 && !busy && (
            <div className="mt-8 flex flex-wrap gap-3">
              <Button variant="outline" disabled={busy} onClick={() => sendQuery("Show me more")}>
                Show me more
              </Button>
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => sendQuery("Something cheaper")}
              >
                Something cheaper
              </Button>
              <Button variant="ghost" asChild>
                <Link to="/menu">Back to menu</Link>
              </Button>
            </div>
          )}

          {/* Below the thread, not inside a turn: the suggestion describes the
              current cart, not the reply above it, so it does not belong to
              any one bubble. Same component as home/cart — one Add/Choose
              decision, one decline path, one wording per `basis`. */}
          <WaiterPrompt placement="chat" />

          <div ref={bottomRef} />
        </div>
      )}

      <form
        className="composer fixed inset-x-0 bottom-[58px] z-30 border-t border-border p-3 lg:bottom-0"
        onSubmit={handleSubmit}
      >
        <div className="mx-auto flex max-w-5xl gap-2 px-4 sm:px-6 lg:px-10">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={hasResult ? "Refine your craving…" : "Something spicy and vegetarian…"}
            className="h-12 flex-1"
          />
          <Button
            type="submit"
            size="icon"
            className="size-12"
            disabled={busy || !draft.trim()}
            aria-label="Send message"
          >
            <Send />
          </Button>
        </div>
      </form>
    </div>
  );
}
