/**
 * Durable traits for a visitor who has no account yet.
 *
 * The concierge is usable before login by design, so a guest can say they are
 * vegetarian and be recommended meat two questions later: they have no row in
 * `users`, so the server has nowhere to keep it. Their browser is the only
 * store available.
 *
 * Only what the server inferred is kept, and only the two fields it is willing
 * to infer — diet and spice level. Cuisine and budget describe the meal rather
 * than the person, and storing "something cheap tonight" would turn one lunch
 * into a permanent budget tier.
 *
 * Every function here swallows storage failures. A browser in private mode
 * costs this visitor a remembered preference; it must never cost them the chat.
 *
 * Spec: docs/superpowers/specs/2026-09-14-guest-preferences-design.md
 */

const GUEST_PREFS_KEY = "bangkok-bowl-guest-prefs";

export type GuestPreferences = {
  diet?: string;
  spice_level?: string;
};

/** The only keys ever stored, so a server that starts sending more cannot
 *  quietly widen what this browser holds. */
const ALLOWED_FIELDS = ["diet", "spice_level"] as const;

function sanitize(value: unknown): GuestPreferences {
  if (!value || typeof value !== "object") return {};
  const source = value as Record<string, unknown>;
  const clean: GuestPreferences = {};
  for (const field of ALLOWED_FIELDS) {
    const raw = source[field];
    // Length-bounded: this is read straight back into a request body, and an
    // unbounded string from storage is an unbounded string on the wire.
    if (typeof raw === "string" && raw.length > 0 && raw.length <= 32) {
      clean[field] = raw;
    }
  }
  return clean;
}

export function readGuestPreferences(): GuestPreferences {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(GUEST_PREFS_KEY);
    return raw ? sanitize(JSON.parse(raw)) : {};
  } catch {
    // Malformed JSON is discarded rather than repaired. Guessing at what a
    // corrupt preference meant is how a wrong diet becomes permanent.
    clearGuestPreferences();
    return {};
  }
}

/**
 * Fold in what the latest turn inferred. Later statements win.
 *
 * Returns the merged value so a caller can use it without a second read.
 */
export function mergeGuestPreferences(inferred: unknown): GuestPreferences {
  const addition = sanitize(inferred);
  if (Object.keys(addition).length === 0) return readGuestPreferences();

  const merged = { ...readGuestPreferences(), ...addition };
  try {
    window.localStorage.setItem(GUEST_PREFS_KEY, JSON.stringify(merged));
  } catch {
    // Nothing remembered across reloads; the merged value still serves this turn.
  }
  return merged;
}

export function clearGuestPreferences(): void {
  try {
    window.localStorage.removeItem(GUEST_PREFS_KEY);
  } catch {
    // Losing the clear is cosmetic. Throwing during login would not be.
  }
}

/** What to send with a chat request, or undefined when there is nothing to say. */
export function guestPreferencesForRequest(): GuestPreferences | undefined {
  const stored = readGuestPreferences();
  return Object.keys(stored).length > 0 ? stored : undefined;
}
