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

const stepKey = (tourId: string, target: string) => `${tourId}:${target}`;

/** The tips of a tour not shown yet (all of them once the tour is done). */
export function unseenTargets(
  seen: Seen,
  tourId: string,
  targets: readonly string[],
): string[] {
  if (isSeen(seen, tourId)) return [];
  return targets.filter(t => !isSeen(seen, stepKey(tourId, t)));
}

/**
 * What a tour leaves behind. Each tip shown is remembered on its own, so a
 * tip that could not be pointed at this time (Home's Today card pushed under
 * the tab bar by waiting orders) still gets its turn later; the tour is done
 * when every tip has been shown, or at once when the rider skips it.
 */
export function afterTour(
  seen: Seen,
  tourId: string,
  targets: readonly string[],
  shown: readonly string[],
  skipped: boolean,
): Seen {
  let next = seen;
  for (const t of shown) next = markSeen(next, stepKey(tourId, t));
  if (skipped || unseenTargets(next, tourId, targets).length === 0)
    next = markSeen(next, tourId);
  return next;
}
