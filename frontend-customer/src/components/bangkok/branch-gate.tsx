import { Clock, MapPin } from "lucide-react";

import { useBangkokStore } from "@/lib/bangkok-store";

/**
 * Pick a branch before seeing a menu.
 *
 * Branches of one restaurant do not carry the same food. Measured on the seeded
 * data: Bangkok Bowl runs 13, 13 and 12 items across its three branches — 17
 * distinct dishes over 38 rows, where stocking everything everywhere would be
 * 51. Momo Mountain runs 8, 9, 9.
 *
 * The app used to choose silently via `pickDefaultLocation`, so a customer
 * could browse, ask the concierge, and add to a cart against a kitchen they
 * never selected and were never shown. Nothing was wrong on screen; it was just
 * someone else's menu.
 *
 * This is a gate, and a gate before any food has a real cost — it is the first
 * thing a new visitor meets. So it is one screen, one tap, with the branch the
 * app would have chosen already highlighted, and it never appears again: the
 * choice persists with the rest of the store state, and the header picker
 * changes it afterwards.
 */
export function BranchGate() {
  const store = useBangkokStore();

  // Nothing to choose between yet. Rendering a gate with no options would trap
  // the visitor behind a screen that cannot be satisfied.
  if (store.branchChosen || store.isRestaurantLoading || store.locations.length === 0) {
    return null;
  }

  return (
    <div className="branch-gate" role="dialog" aria-modal="true" aria-labelledby="branch-gate-title">
      <div className="branch-gate__panel">
        <span className="brand-mark">BB</span>
        <h1 id="branch-gate-title" className="font-display text-3xl font-extrabold sm:text-4xl">
          Which branch are you ordering from?
        </h1>
        <p className="mt-2 text-muted">
          Menus and opening hours differ by branch, so we will only show you what
          this kitchen can actually make.
        </p>

        <ul className="branch-gate__list">
          {store.locations.map((location) => {
            // The pre-selection, shown as a hint rather than acted on.
            const suggested = location.id === store.branchId;
            return (
              <li key={location.id}>
                <button
                  type="button"
                  className={`branch-gate__option${suggested ? " is-suggested" : ""}`}
                  onClick={() => store.setBranchId(location.id)}
                >
                  <MapPin className="size-4 shrink-0 text-primary" />
                  <span className="min-w-0 flex-1 text-left">
                    <span className="branch-gate__name">{location.branch_name}</span>
                    <span className="branch-gate__meta">
                      <Clock className="size-3.5" />
                      {location.is_open ? "Open now" : "Closed"}
                    </span>
                  </span>
                  {suggested && <span className="branch-gate__hint">Nearest</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
