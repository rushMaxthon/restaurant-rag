import { useEffect } from 'react';
import { useIsFocused } from '@react-navigation/native';

import { useRider } from '@/store/RiderProvider';
import { useGuide } from './GuideProvider';
import { isSeen } from './guideStore';
import type { TourId } from './tours';

/** Layout settles after a screen's entering animations; measuring before that points at mid-air. */
const SETTLE_MS = 700;

/**
 * Runs a screen's tour the first time it is on screen with its data in
 * place. `ready` is the screen's own "there is something to point at" -
 * Orders passes "the list is not empty", Trip passes "the step this tour
 * is about". Seen is written when the tour ends, by Done or by Skip.
 */
export function useTour(id: TourId, ready: boolean = true): void {
  const focused = useIsFocused();
  const { loaded, seen, active, start } = useGuide();
  const { offer } = useRider();
  const due =
    focused && ready && loaded && !active && !offer && !isSeen(seen, id);

  useEffect(() => {
    if (!due) return;
    const t = setTimeout(() => start(id), SETTLE_MS);
    return () => clearTimeout(t);
  }, [due, id, start]);
}
