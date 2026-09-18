import { useEffect, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { AlertCircle, Check, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError, api, type UserPreferencesPayload } from "@/lib/api";
import { useRequireAuth } from "@/lib/require-auth";
import { pageMeta } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

export const Route = createFileRoute("/preferences")({
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Your preferences", "Tell us what you like so the menu suits you."),
  }),
  component: PreferencesPage,
});

/**
 * Where a customer changes how they eat.
 *
 * There was no way to. The API has always supported it — `PUT
 * /preferences/me` works, and mobile has a form — but the web app's only write
 * was `promoteGuestPreferences`, which deliberately does nothing when the
 * account already has preferences ("account wins"). Between the two, a diet set
 * once could never be changed on the web: not by the chat, not by signing in,
 * not by a guest session.
 *
 * Saying "I want non veg" in the chat still overrides for that turn — the
 * message always beats the stored preference — but it was never written down,
 * so the next turn reverted. That is the behaviour this replaces.
 */

const DIETS = [
  { value: "VEG", label: "Vegetarian" },
  { value: "NON_VEG", label: "Non-vegetarian" },
] as const;

const SPICE = [
  { value: "LOW", label: "Mild" },
  { value: "MEDIUM", label: "Medium" },
  { value: "HIGH", label: "Spicy" },
] as const;

const BUDGET = [
  { value: "LOW", label: "Budget" },
  { value: "MID", label: "Mid-range" },
  { value: "HIGH", label: "Premium" },
] as const;

const CUISINES = ["American", "Chinese", "Indian", "Italian", "Thai", "Tibetan"];

type Status = "loading" | "ready" | "saving" | "saved" | "error";

function PreferencesPage() {
  const isAuthenticated = useRequireAuth();

  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string | null>(null);
  const [diet, setDiet] = useState<string | null>(null);
  const [spice, setSpice] = useState<string | null>(null);
  const [budget, setBudget] = useState<string | null>(null);
  const [cuisines, setCuisines] = useState<string[]>([]);
  // Held but never edited here. The payload REPLACES every column, so a field
  // this screen does not show still has to be sent back or saving would clear
  // it — silently losing whatever the mobile app or onboarding had set.
  const [favoriteItems, setFavoriteItems] = useState<string[]>([]);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    void (async () => {
      const existing = await api.getMyPreferences();
      if (cancelled) return;
      if (existing) {
        setDiet(existing.diet ?? null);
        setSpice(existing.spice_level ?? null);
        setBudget(existing.budget ?? null);
        setCuisines(existing.cuisines ?? []);
        setFavoriteItems(existing.favorite_items ?? []);
      }
      // A customer with no row yet is not an error — it is the common case for
      // a new account, and the form simply starts empty.
      setStatus("ready");
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  function toggleCuisine(name: string) {
    setStatus("ready");
    setCuisines((current) =>
      current.includes(name) ? current.filter((c) => c !== name) : [...current, name],
    );
  }

  async function save() {
    setStatus("saving");
    setError(null);
    const payload: UserPreferencesPayload = {
      diet,
      spice_level: spice,
      budget,
      cuisines,
      favorite_items: favoriteItems,
    };
    try {
      await api.putMyPreferences(payload);
      setStatus("saved");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save. Please try again.");
      setStatus("error");
    }
  }

  if (!isAuthenticated) return null;

  return (
    <div className="page-pad mx-auto max-w-3xl py-10 pb-32">
      <Sparkles className="mb-4 size-8 text-primary" />
      <h1 className="font-display text-3xl font-extrabold sm:text-4xl">Your preferences</h1>
      <p className="mt-3 max-w-xl text-lg text-muted">
        The concierge uses these on every question, so you don't have to repeat
        yourself. You can still ask for something different any time — what you
        say wins over what's saved here.
      </p>

      {status === "loading" ? (
        <p className="mt-8 flex items-center gap-2 text-muted">
          <Loader2 className="size-4 animate-spin" /> Loading…
        </p>
      ) : (
        <>
          <Choice
            label="Diet"
            options={DIETS}
            value={diet}
            onChange={(v) => {
              setStatus("ready");
              setDiet(v);
            }}
          />
          <Choice
            label="Spice"
            options={SPICE}
            value={spice}
            onChange={(v) => {
              setStatus("ready");
              setSpice(v);
            }}
          />
          <Choice
            label="Budget"
            options={BUDGET}
            value={budget}
            onChange={(v) => {
              setStatus("ready");
              setBudget(v);
            }}
          />

          <fieldset className="mt-8">
            <legend className="text-sm font-bold uppercase tracking-wide text-muted">
              Favourite cuisines
            </legend>
            <div className="mt-3 flex flex-wrap gap-2">
              {CUISINES.map((name) => (
                <button
                  key={name}
                  type="button"
                  aria-pressed={cuisines.includes(name)}
                  onClick={() => toggleCuisine(name)}
                  className={`category-pill${cuisines.includes(name) ? " active" : ""}`}
                >
                  {name}
                </button>
              ))}
            </div>
          </fieldset>

          {error && (
            <div className="inline-error form-error mt-6" role="alert">
              <AlertCircle className="mt-0.5 size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <div className="mt-8 flex items-center gap-3">
            <Button onClick={save} disabled={status === "saving"}>
              {status === "saving" ? "Saving…" : "Save preferences"}
            </Button>
            {status === "saved" && (
              <span className="flex items-center gap-1 text-sm font-bold text-primary" role="status">
                <Check className="size-4" /> Saved
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * A single-choice row where the selected option can be turned OFF again.
 *
 * Tapping the active choice clears it, because "no preference" is a real answer
 * and a form that cannot express it forces everyone into a category. The
 * backend treats null as unset rather than as a default.
 */
function Choice({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly { value: string; label: string }[];
  value: string | null;
  onChange: (value: string | null) => void;
}) {
  return (
    <fieldset className="mt-8">
      <legend className="text-sm font-bold uppercase tracking-wide text-muted">{label}</legend>
      <div className="mt-3 flex flex-wrap gap-2">
        {options.map((option) => {
          const selected = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              aria-pressed={selected}
              onClick={() => onChange(selected ? null : option.value)}
              className={`category-pill${selected ? " active" : ""}`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}
