import { useState, type Dispatch, type SetStateAction } from 'react';

import { useAdminStore } from './useAdminStore';

/**
 * A restaurant filter that follows the shell's tenant switcher but can still
 * be pointed somewhere else.
 *
 * Three list screens want the same behaviour: start on whatever restaurant the
 * operator is working on, move when they move the switcher, and let the
 * screen's own dropdown override it — because "all restaurants" is a real
 * answer on a list of offers in a way it is not on a diagnosis.
 *
 * Written as a render-time adjustment rather than an effect. Mirroring a value
 * into state with `useEffect` renders once with the stale filter and once more
 * with the right one, so the list visibly shows the wrong restaurant's rows
 * for a frame; comparing during render means the corrected value is what gets
 * painted. It is also what `react-hooks/set-state-in-effect` is pointing at.
 *
 * `allValue` differs per screen — Reports uses `""` where Offers and Generated
 * Combos use `"ALL"` — so it is a parameter rather than a constant here.
 * Unifying those sentinels is a bigger change than this one.
 *
 * `pinnedRestaurantId` is an owner's own restaurant: they have no switcher and
 * nothing to follow, so the filter stays where it was put.
 */
export function useScopedRestaurantFilter(
  allValue: string,
  pinnedRestaurantId?: string | null,
): [string, Dispatch<SetStateAction<string>>] {
  const { activeRestaurantId } = useAdminStore();
  const follows = pinnedRestaurantId ? null : activeRestaurantId;

  const [filter, setFilter] = useState<string>(
    () => pinnedRestaurantId ?? activeRestaurantId ?? allValue,
  );
  // What the switcher said when this filter was last seeded. Kept in state
  // rather than a ref so the comparison below happens during render.
  const [seen, setSeen] = useState<string | null>(follows);

  if (seen !== follows) {
    setSeen(follows);
    setFilter(follows ?? allValue);
  }

  return [filter, setFilter];
}
