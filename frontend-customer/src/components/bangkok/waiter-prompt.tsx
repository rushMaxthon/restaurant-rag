import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useBangkokStore } from "@/lib/bangkok-store";
import { readChatSession, storeChatSession } from "@/lib/chat-session";
import { useMenuItem } from "@/lib/queries";
import { cartLinesForRequest, suggestionCopy, type SellSuggestion } from "@/lib/suggestions";

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
export function WaiterPrompt({ placement }: { placement: "home" | "cart" }) {
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
  }, [locationId, sessionId, store.cart]);

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

  return (
    <aside className={`waiter-prompt waiter-prompt--${placement}`} role="note">
      <p className="waiter-prompt__text">{suggestionCopy(suggestion, item.name, item.category)}</p>
      <div className="waiter-prompt__actions">
        <Button size="sm" onClick={() => store.addItem(item)}>
          Add
        </Button>
        <Button size="sm" variant="ghost" onClick={dismiss} aria-label="No thanks">
          <X />
        </Button>
      </div>
    </aside>
  );
}
