/**
 * Which parts of the guide this phone has already shown.
 *
 * A flat map of tour id → true, kept in AsyncStorage. Decoding is strict
 * about shape and forgiving about garbage: a corrupt value must mean "show
 * the guide again", never "hide it forever".
 */

export const SEEN_KEY = 'rider.guide.v1';

export type Seen = Record<string, true>;

export function decodeSeen(raw: string | null): Seen {
  if (!raw) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
      return {};
    const out: Seen = {};
    for (const [key, value] of Object.entries(parsed)) {
      if (value === true) out[key] = true;
    }
    return out;
  } catch {
    return {};
  }
}

export function encodeSeen(seen: Seen): string {
  return JSON.stringify(seen);
}

export function isSeen(seen: Seen, id: string): boolean {
  return seen[id] === true;
}

export function markSeen(seen: Seen, id: string): Seen {
  return { ...seen, [id]: true };
}

/** "Show tips again": every spotlight tour, but not the intro - that has its own row. */
export function resetAll(seen: Seen): Seen {
  return seen.intro ? { intro: true } : {};
}
