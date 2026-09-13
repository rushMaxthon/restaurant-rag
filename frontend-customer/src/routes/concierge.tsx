import { useEffect, useRef, useState } from "react";
import { Link, createFileRoute, useNavigate, useRouterState } from "@tanstack/react-router";
import { AlertCircle, ArrowLeft, Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DishCard } from "@/components/bangkok/dish-card";
import { DishSkeleton } from "@/components/bangkok/menu-grid";
import heroImage from "@/assets/mango-sticky-rice.jpg";
import { ApiError, streamChatMessage, type ChatSuggestion } from "@/lib/api";
import type { MenuItem } from "@/lib/bangkok-data";

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
  const [suggestions, setSuggestions] = useState<ChatSuggestion[]>([]);
  const [reply, setReply] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const autoSentRef = useRef(false);

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

  async function sendQuery(message: string) {
    const text = message.trim();
    if (!text || status === "waiting" || status === "streaming") return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setError(null);
    setStatus("waiting");
    setReply("");
    setDraft("");

    try {
      await streamChatMessage(
        { message: text, session_id: sessionIdRef.current },
        {
          onMeta: (meta) => {
            sessionIdRef.current = meta.session_id;
            setSuggestions(meta.suggestions);
            setStatus((s) => (s === "waiting" ? "streaming" : s));
          },
          onToken: (chunk) => {
            setReply((prev) => prev + chunk);
          },
          onDone: (done) => {
            sessionIdRef.current = done.session_id;
            setSuggestions(done.suggestions);
            setReply(done.reply);
            setStatus("done");
          },
        },
        controller.signal,
      );
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
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

  const hasResult = status !== "idle";
  const busy = status === "waiting" || status === "streaming";

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
          <button onClick={() => setStatus("idle")} className="back-link mb-4">
            <ArrowLeft className="size-4" /> Ask something else
          </button>

          <h1 className="font-display text-3xl font-black sm:text-4xl">
            Here's what we found for you
          </h1>

          {reply && (
            <p className="concierge-reply mt-4 max-w-3xl text-lg text-muted" aria-live="polite">
              {stripMarkdown(reply)}
              {status === "streaming" && <span className="stream-caret" aria-hidden="true" />}
            </p>
          )}
          {status === "waiting" && (
            <p className="typing mt-4 text-lg" role="status">
              <span className="typing-dots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              Finding dishes for you…
            </p>
          )}

          {error && (
            <div className="inline-error form-error mt-4" role="alert">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {status === "waiting" && suggestions.length === 0 ? (
            <div className="mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <DishSkeleton key={i} />
              ))}
            </div>
          ) : (
            suggestions.length > 0 && (
              <div className="menu-grid mt-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {suggestions.map((s, i) => (
                  <div className="rise-in" style={{ "--i": i } as React.CSSProperties} key={s.id}>
                    <DishCard item={suggestionToMenuItem(s)} />
                  </div>
                ))}
              </div>
            )
          )}

          {suggestions.length > 0 && (
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
