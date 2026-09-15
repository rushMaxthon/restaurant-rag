import { useEffect, useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "@/components/bangkok/dish-image";
import { VegMark } from "@/components/bangkok/veg-mark";
import { api } from "@/lib/api";
import { formatMoney } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { readChatSession, storeChatSession } from "@/lib/chat-session";
import { useMenuItem } from "@/lib/queries";
import {
  cartLinesForRequest,
  cartSuggestionSignature,
  suggestionCopy,
  suggestionNeedsChoice,
  suggestionReason,
  type SellSuggestion,
} from "@/lib/suggestions";

/**
 * One suggestion, rendered where the customer already is.
 *
 * Deliberately NOT a chat. There is no transcript, no input and no history:
 * a single line with one action and a dismiss. A customer who ignores it sees
 * the site exactly as it was, because guidance here is additive and never
 * gates a path. The design constraint is the page keeps doing what it does —
 * this only makes the components already on it say something.
 *
 * Dismissing counts as a decline, and two declines silence suggestions for the
 * session — which is why the dismiss button posts rather than only hiding.
 */
export function WaiterPrompt({ placement }: { placement: "home" | "cart" | "chat" }) {
  const store = useBangkokStore();
  const [suggestion, setSuggestion] = useState<SellSuggestion | null>(null);

  const locationId = store.orderLocation?.id;

  // Minted here when the customer has never chatted, because guidance must not
  // require a conversation to have happened first. Shares chat-session.ts's
  // storage key with /concierge, so a decline recorded here silences the same
  // session there, and vice versa.
  const sessionId = useMemo(() => {
    if (typeof window === "undefined") return null;
    const existing = readChatSession();
    if (existing) return existing;
    const minted = crypto.randomUUID();
    storeChatSession(minted);
    return minted;
  }, []);

  // What actually affects the answer (item, size, option ids) — NOT
  // `store.cart` itself. `changeQuantity` returns a new array on every tap,
  // and `CartLineFacts` on the backend has no quantity field, so keying this
  // effect on the array would refire on a change guaranteed not to change the
  // result — burning a `record_offer` + `store_memory` call, and on the cart
  // page draining the session's two-decline suppression budget, for nothing.
  const cartSignature = useMemo(() => cartSuggestionSignature(store.cart), [store.cart]);

  useEffect(() => {
    if (!locationId || !sessionId) return;
    let cancelled = false;
    void (async () => {
      try {
        const next = await api.getSuggestion({
          restaurantLocationId: locationId,
          sessionId,
          cart: cartLinesForRequest(store.cart),
        });
        if (!cancelled) setSuggestion(next);
      } catch {
        // Guidance must never break a page. Silence is the correct failure —
        // no error surfaces, the page renders exactly as it would without this.
        if (!cancelled) setSuggestion(null);
      }
    })();
    return () => {
      cancelled = true;
    };
    // store.cart is read inside (for the request payload) but deliberately
    // absent here — cartSignature is the derived value that should trigger a
    // refetch; see its docstring in suggestions.ts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locationId, sessionId, cartSignature]);

  // The name, category and price come from the client's OWN menu data, never
  // from the suggestion — one price path, so this can never contradict the
  // menu page. Called unconditionally: a hook above an early return is a
  // runtime error, not a style issue.
  const { data: item } = useMenuItem(suggestion?.menu_item_id ?? undefined);

  // Silently drop a suggestion this branch's menu doesn't actually resolve —
  // a combo-only basis with no menu_item_id, or an item from another location
  // slipping through — rather than rendering an "Add" button that would fail.
  if (!suggestion || !item || item.restaurant_location_id !== locationId) return null;

  async function dismiss() {
    setSuggestion(null);
    if (sessionId && suggestion?.menu_item_id) {
      try {
        await api.declineSuggestion(sessionId, suggestion.menu_item_id);
      } catch {
        // A decline that fails to record is not worth telling the customer about.
      }
    }
  }

  // A one-line prompt has nothing to choose a size or an add-on with — the
  // same reason `dish-card.tsx` sends a sized or customizable dish to its own
  // page instead of adding it. `size_upgrade` and `add_on` are never a plain
  // add at all (the item named is already in the cart; the change is the
  // size or option, which only the dish page can collect), and a cross-sold
  // item that itself has sizes or customizations hits the identical problem
  // from the other direction. Routing to the dish page is the honest choice
  // both times, not a limitation of the prompt.
  const needsChoice = suggestionNeedsChoice(suggestion, item);

  return (
    // aria-label carries `suggestionCopy` — one coherent sentence with the item
    // name in it — as the accessible name, even though the visible markup now
    // splits reason, name and price into separate nodes. Without it a screen
    // reader would read three disconnected fragments instead of the sentence
    // this copy was written to be.
    <aside
      className={`waiter-prompt waiter-prompt--${placement}`}
      role="note"
      aria-live="polite"
      aria-label={suggestionCopy(suggestion, item.name, item.category)}
    >
      {/*
        The same DishImage the menu grid and dish page use, so a null
        `image_url` — common in this data — falls back to the same
        initials-on-a-tint tile customers already see elsewhere, not a
        second, ad hoc "broken image" look invented just for this row.
        Tailwind classes override DishImage's own aspect-[4/3]/w-full/
        text-3xl defaults via tailwind-merge: square, ~56px, small text.
      */}
      <DishImage
        src={item.image_url}
        name={item.name}
        className="waiter-prompt__thumb aspect-square h-14 w-14 shrink-0 rounded-lg text-sm"
      />
      <div className="waiter-prompt__text" aria-hidden="true">
        <span className="waiter-prompt__reason">{suggestionReason(suggestion, item.category)}</span>
        <span className="waiter-prompt__name">
          <VegMark veg={item.is_veg} />
          {item.name}
        </span>
        <span className="waiter-prompt__price">{formatMoney(item.price)}</span>
      </div>
      <div className="waiter-prompt__actions">
        {needsChoice ? (
          <Button size="sm" variant="outline" asChild>
            <Link to="/menu/$itemId" params={{ itemId: item.id }}>
              Choose
            </Link>
          </Button>
        ) : (
          <Button size="sm" onClick={() => store.addItem(item)}>
            Add
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={dismiss} aria-label="No thanks">
          <X />
        </Button>
      </div>
    </aside>
  );
}
