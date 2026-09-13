import { useEffect, useRef, useState } from "react";
import { createFileRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import { AlertCircle, Send, Sparkles, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DishCard } from "@/components/bangkok/dish-card";
import heroImage from "@/assets/mango-sticky-rice.jpg";
import { useAuth } from "@/lib/auth";
import { useSendChatMessage } from "@/lib/queries";
import { ApiError, type ChatSuggestion } from "@/lib/api";
import type { MenuItem } from "@/lib/bangkok-data";

type ConciergeSearch = { q?: string };

export const Route = createFileRoute("/concierge")({
  validateSearch: (search: Record<string, unknown>): ConciergeSearch =>
    typeof search["q"] === "string" ? { q: search["q"] as string } : {},
  head: () => ({
    meta: [
      { title: "Food Concierge — Bangkok Bowl" },
      { name: "description", content: "Tell our AI food concierge your mood and get Bangkok Bowl dish picks." },
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

type ChatTurn = { role: "user" | "assistant"; text: string; suggestions?: ChatSuggestion[] };

const STARTERS = ["Something spicy and vegetarian", "A light lunch under 300 rupees", "Comfort food for a rainy day"];

function ConciergePage() {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.href });
  const search = Route.useSearch();
  const sendMessage = useSendChatMessage();
  const sessionIdRef = useRef<string>(crypto.randomUUID());
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const autoSentRef = useRef(false);

  useEffect(() => {
    if (!isAuthenticated) navigate({ to: "/login", search: { redirect: pathname } });
  }, [isAuthenticated, navigate, pathname]);

  // A craving chip on the home screen deep-links here with ?q=... — send it
  // immediately rather than just dropping it in the box, then drop the param
  // so a back-navigation or refresh doesn't resend it.
  useEffect(() => {
    if (!isAuthenticated || !search.q || autoSentRef.current) return;
    autoSentRef.current = true;
    const message = search.q;
    navigate({ to: "/concierge", search: {}, replace: true });
    void sendText(message);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, search.q]);

  if (!isAuthenticated) return null;

  async function sendText(message: string) {
    if (!message.trim() || sendMessage.isPending) return;
    setError(null);
    setTurns((t) => [...t, { role: "user", text: message }]);
    setDraft("");
    try {
      const response = await sendMessage.mutateAsync({ message, session_id: sessionIdRef.current });
      setTurns((t) => [...t, { role: "assistant", text: response.reply, suggestions: response.suggestions }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The concierge is unavailable right now. Please try again.");
    }
  }

  async function handleSend(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await sendText(draft);
  }

  return (
    <div className="pb-32">
      <section className="relative min-h-[38svh] overflow-hidden">
        <img src={heroImage} alt="Mango sticky rice at Bangkok Bowl" className="absolute inset-0 size-full object-cover" />
        <div className="hero-overlay absolute inset-0" />
        <div className="page-pad relative flex min-h-[38svh] max-w-3xl flex-col justify-end pb-10 pt-24 text-primary-foreground">
          <Sparkles className="mb-4 size-10" />
          <h1 className="font-display text-5xl font-black leading-[.98] sm:text-6xl">Ask the food concierge</h1>
          <p className="mt-4 max-w-xl text-lg font-medium">Describe what you're craving and get real picks from the Bangkok Bowl menu.</p>
        </div>
      </section>

      <div className="page-pad mx-auto max-w-5xl py-10">
        {turns.length === 0 && (
          <div className="mb-8 flex flex-wrap gap-2">
            {STARTERS.map((s) => (
              <button key={s} onClick={() => sendText(s)} className="category-pill">
                {s}
              </button>
            ))}
          </div>
        )}

        <div className="space-y-6">
          {turns.length === 0 && (
            <div className="surface-panel flex items-start gap-3 p-5">
              <span className="brand-mark shrink-0">BB</span>
              <p className="pt-2 text-lg">Tell me your mood—spicy, comforting, light—and I'll point you to a bowl.</p>
            </div>
          )}
          {turns.map((turn, i) =>
            turn.role === "user" ? (
              <div key={i} className="flex justify-end">
                <div className="flex max-w-[85%] items-start gap-3">
                  <div className="rounded-lg rounded-tr-sm bg-primary px-5 py-3 text-primary-foreground">
                    <p>{turn.text}</p>
                  </div>
                  <span className="mt-1 flex size-8 shrink-0 items-center justify-center rounded-full bg-surface-alt">
                    <UserRound className="size-4" />
                  </span>
                </div>
              </div>
            ) : (
              <div key={i} className="flex items-start gap-3">
                <span className="brand-mark mt-1 shrink-0">BB</span>
                <div className="max-w-[85%] rounded-lg rounded-tl-sm border border-border bg-surface px-5 py-3">
                  <p>{turn.text}</p>
                  {turn.suggestions && turn.suggestions.length > 0 && (
                    <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                      {turn.suggestions.map((s) => (
                        <DishCard key={s.id} item={suggestionToMenuItem(s)} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ),
          )}
          {sendMessage.isPending && (
            <div className="flex items-start gap-3">
              <span className="brand-mark mt-1 shrink-0">BB</span>
              <div className="rounded-lg rounded-tl-sm border border-border bg-surface px-5 py-3 text-muted">The concierge is thinking…</div>
            </div>
          )}
          {error && (
            <div className="flex items-start gap-2 rounded-md border border-danger bg-danger/10 p-3 text-sm font-semibold text-danger">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}
        </div>
      </div>

      <form className="fixed inset-x-0 bottom-[58px] z-30 border-t border-border bg-surface p-3 lg:bottom-0" onSubmit={handleSend}>
        <div className="mx-auto flex max-w-5xl gap-2 px-4 sm:px-6 lg:px-10">
          <Input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Something spicy and vegetarian…" className="h-12 flex-1" />
          <Button type="submit" size="icon" className="size-12" disabled={sendMessage.isPending || !draft.trim()} aria-label="Send message">
            <Send />
          </Button>
        </div>
      </form>
    </div>
  );
}
