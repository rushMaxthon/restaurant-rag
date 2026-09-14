import { useEffect, useRef, useState } from "react";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { AlertCircle, ArrowLeft, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DishCard } from "@/components/bangkok/dish-card";
import { DishSkeleton } from "@/components/bangkok/menu-grid";
import heroImage from "@/assets/mango-sticky-rice.jpg";
import {
  ApiError,
  getChatHistory,
  getToken,
  streamChatMessage,
  type ChatSuggestion,
} from "@/lib/api";
import type { MenuItem } from "@/lib/bangkok-data";
import { guestPreferencesForRequest, mergeGuestPreferences } from "@/lib/guest-preferences";

type ConciergeSearch = { q?: string };

export const Route = createFileRoute("/concierge")({
  validateSearch: (search: Record<string, unknown>): ConciergeSearch =>
    typeof search["q"] === "string" ? { q: search["q"] as string } : {},
  head: () => ({
    meta: [
      { title: "Food Concierge — Bangkok Bowl" },
      {
        name: "description",
        content: "Tell our AI food concierge your mood and get Bangkok Bowl dish picks.",
      },
      { property: "og:title", content: "Food Concierge — Bangkok Bowl" },
      { property: "og:type", content: "website" },
    ],
  }),
  component: ConciergePage,
});

function suggestionToMenuItem(s: ChatSuggestion): MenuItem {
  return {
    id: s.id,
    restaurant_id: s.restaurant_id,
    restaurant_location_id: s.restaurant_location_id,
    name: s.name,
    category: s.category,
    cuisine_type: s.cuisine_type ?? "",
    description: s.description ?? "",
    price: s.price,
    is_veg: s.is_veg,
    is_available: s.is_available,
    is_bestseller: s.is_bestseller ?? false,
    image_url: s.image_url,
    rating: null,
    rating_count: 0,
    is_new: s.is_new ?? false,
    is_favorite: s.is_favorite ?? false,
    has_sizes: false,
    has_customizations: false,
    sizes: [],
    customization_groups: [],
  };
}

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
type Turn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  suggestions: ChatSuggestion[];
};

/**
 * The session this browser is continuing.
 *
 * Held in localStorage, not just a ref: the backend has always written every
 * turn to `chat_history` keyed by session, so the only thing standing between a
 * reload and the conversation coming back was the client forgetting which
 * session it had been in.
 */
const SESSION_KEY = "bangkok-bowl-chat-session";

function readStoredSession(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function storeSession(sessionId: string): void {
  try {
    window.localStorage.setItem(SESSION_KEY, sessionId);
  } catch {
    // A browser refusing storage costs continuity across reloads, nothing more.
  }
}

function clearStoredSession(): void {
  try {
    window.localStorage.removeItem(SESSION_KEY);
  } catch {
    // Same as above: losing the reset is cosmetic, throwing here would not be.
  }
}

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
  const navigate = useNavigate();
  const search = Route.useSearch();

  const [status, setStatus] = useState<Status>("idle");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const autoSentRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  // Replay the conversation the backend kept. Only for a signed-in customer:
  // a guest's turns are keyed to a session id that dies with the tab, so there
  // is nothing on the server to ask for.
  useEffect(() => {
    if (!getToken()) return;
    const stored = readStoredSession();
    if (!stored) return;
    sessionIdRef.current = stored;

    let cancelled = false;
    void (async () => {
      try {
        const history = await getChatHistory(stored);
        if (cancelled || history.length === 0) return;
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
  }, []);

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
          // Undefined for a signed-in customer and for a guest who has said
          // nothing yet. The backend ignores it outright for an account, so
          // sending it would be harmless — but not sending what cannot be used
          // keeps the request honest about who it is for.
          guest_preferences: getToken() ? undefined : guestPreferencesForRequest(),
        },
        {
          onMeta: (meta) => {
            sessionIdRef.current = meta.session_id;
            storeSession(meta.session_id);
            // Only ever non-empty for a guest; see ChatStreamMeta.
            mergeGuestPreferences(meta.inferred_preferences);
            patchAnswer((turn) => ({ ...turn, suggestions: meta.suggestions }));
            setStatus((s) => (s === "waiting" ? "streaming" : s));
          },
          onToken: (chunk) => {
            patchAnswer((turn) => ({ ...turn, text: turn.text + chunk }));
          },
          onDone: (done) => {
            sessionIdRef.current = done.session_id;
            storeSession(done.session_id);
            patchAnswer((turn) => ({ ...turn, text: done.reply, suggestions: done.suggestions }));
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
    clearStoredSession();
    setTurns([]);
    setError(null);
    setDraft("");
    setStatus("idle");
  }

  const hasResult = turns.length > 0 || status !== "idle";
  const busy = status === "waiting" || status === "streaming";
  const lastSuggestions =
    [...turns].reverse().find((t) => t.suggestions.length > 0)?.suggestions ?? [];

  return (
    <div className="pb-32">
      {!hasResult ? (
        <>
          <section className="relative min-h-[38svh] overflow-hidden">
            <img
              src={heroImage}
              alt="Mango sticky rice at Bangkok Bowl"
              className="absolute inset-0 size-full object-cover"
            />
            <div className="hero-overlay absolute inset-0" />
            <div className="hero-copy page-pad relative flex min-h-[38svh] max-w-3xl flex-col justify-end pb-10 pt-24 text-primary-foreground">
              <Sparkles className="mb-4 size-10" />
              <h1 className="font-display text-5xl font-black leading-[.98] sm:text-6xl">
                Ask the food concierge
              </h1>
              <p className="mt-4 max-w-xl text-lg font-medium">
                Describe what you're craving and get real picks from the Bangkok Bowl menu.
              </p>
            </div>
          </section>
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
              const isStreamingAnswer =
                turn.role === "assistant" && index === turns.length - 1 && busy;

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
                          {isStreamingAnswer && (
                            <span className="stream-caret" aria-hidden="true" />
                          )}
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

                  {isStreamingAnswer && turn.suggestions.length === 0 ? (
                    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                      {Array.from({ length: 3 }).map((_, i) => (
                        <DishSkeleton key={i} />
                      ))}
                    </div>
                  ) : (
                    turn.suggestions.length > 0 && (
                      <div className="menu-grid grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                        {turn.suggestions.map((s, i) => (
                          <div
                            className="rise-in"
                            style={{ "--i": i } as React.CSSProperties}
                            key={s.id}
                          >
                            <DishCard item={suggestionToMenuItem(s)} />
                          </div>
                        ))}
                      </div>
                    )
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
