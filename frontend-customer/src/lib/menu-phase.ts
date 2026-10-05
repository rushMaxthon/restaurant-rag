/**
 * What the menu screen should be showing: skeletons, an apology, an empty
 * state, or the dishes.
 *
 * It was two booleans read off TanStack Query — `isLoading` and `isError` —
 * and everything that was neither fell through to "Nothing matches that".
 * Plenty is neither. `isLoading` means "fetching for the first time", so a
 * query that has not started is not loading: one that is disabled because the
 * restaurant has not arrived, one rendered on the server, one on the first
 * client render before its effect has run. On a slow first load that gap is
 * seconds long, and for all of it the page told the customer the restaurant
 * sells nothing.
 *
 * So this asks the other question — has the answer arrived — and treats
 * every "not yet" as loading. Empty is a claim about the restaurant, and it
 * is only made once there is an answer to base it on.
 */
export type MenuPhase = "loading" | "failed" | "empty" | "ready";

export interface MenuPhaseInput {
  /** The restaurant or the menu request came back as an error. */
  failed: boolean;
  /** The restaurant and its branches have not arrived yet. */
  restaurantPending: boolean;
  /** There is a branch to ask for a menu. */
  hasBranch: boolean;
  /** The menu itself has not arrived yet. */
  menuPending: boolean;
  /** Dishes left after the search box and the filters. */
  shown: number;
}

export function menuPhase({
  failed,
  restaurantPending,
  hasBranch,
  menuPending,
  shown,
}: MenuPhaseInput): MenuPhase {
  // First: a failure upstream leaves everything after it pending for good.
  if (failed) return "failed";
  if (restaurantPending) return "loading";
  // No branch means the menu request is never made, so waiting on it would
  // be skeletons forever.
  if (!hasBranch) return "empty";
  if (menuPending) return "loading";
  return shown > 0 ? "ready" : "empty";
}
