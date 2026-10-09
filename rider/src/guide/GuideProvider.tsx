import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Dimensions, View, type StyleProp, type ViewStyle } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { useRider } from '@/store/RiderProvider';
import {
  decodeSeen,
  encodeSeen,
  isSeen,
  markSeen,
  resetAll,
  SEEN_KEY,
  type Seen,
} from './guideStore';
import { inWindow, type Rect } from './placement';
import {
  INTRO_ID,
  TOURS,
  type TargetId,
  type TourId,
  type TourStep,
} from './tours';

/**
 * The guide's state: which tours this phone has seen, which controls are on
 * screen right now (registered by `GuideTarget`), and the tour in progress.
 *
 * One tour at a time, and never over an order ringing: the offer screen is
 * the one thing a rider must never have covered, so an offer arriving ends
 * the tour on the spot. A step whose control is not on screen is skipped
 * rather than shown pointing at nothing.
 */

/** What a `View` ref actually holds on the new architecture. */
type Host = React.ComponentRef<typeof View>;

type Measured = { step: TourStep; rect: Rect };

export type ActiveTour = {
  id: TourId;
  steps: Measured[];
  index: number;
};

type GuideContextValue = {
  loaded: boolean;
  seen: Seen;
  active: ActiveTour | null;
  register: (id: TargetId, ref: React.RefObject<Host | null>) => () => void;
  start: (id: TourId) => void;
  next: () => void;
  skip: () => void;
  /** Drop the tour without marking it seen: the screen went away under it. */
  cancel: () => void;
  markIntroSeen: () => void;
  resetTips: () => void;
};

const GuideContext = createContext<GuideContextValue | null>(null);

function measure(ref: React.RefObject<Host | null>): Promise<Rect | null> {
  return new Promise(resolve => {
    const node = ref.current;
    if (!node) return resolve(null);
    node.measureInWindow((x, y, width, height) => {
      resolve(width > 0 && height > 0 ? { x, y, width, height } : null);
    });
  });
}

export function GuideProvider({ children }: { children: React.ReactNode }) {
  const { offer } = useRider();
  const [seen, setSeen] = useState<Seen>({});
  const [loaded, setLoaded] = useState(false);
  const [active, setActive] = useState<ActiveTour | null>(null);
  const targets = useRef(new Map<TargetId, React.RefObject<Host | null>>());
  const starting = useRef(false);

  useEffect(() => {
    AsyncStorage.getItem(SEEN_KEY)
      .then(raw => setSeen(decodeSeen(raw)))
      .catch(() => {})
      .finally(() => setLoaded(true));
  }, []);

  const persist = useCallback((next: Seen) => {
    setSeen(next);
    AsyncStorage.setItem(SEEN_KEY, encodeSeen(next)).catch(() => {});
  }, []);

  const register = useCallback(
    (id: TargetId, ref: React.RefObject<Host | null>) => {
      targets.current.set(id, ref);
      return () => {
        if (targets.current.get(id) === ref) targets.current.delete(id);
      };
    },
    [],
  );

  const finish = useCallback((id: TourId) => {
    setActive(null);
    setSeen(current => {
      const next = markSeen(current, id);
      AsyncStorage.setItem(SEEN_KEY, encodeSeen(next)).catch(() => {});
      return next;
    });
  }, []);

  const start = useCallback(
    (id: TourId) => {
      if (starting.current || active || isSeen(seen, id)) return;
      starting.current = true;
      const steps = TOURS[id].steps;
      const window = Dimensions.get('window');
      Promise.all(
        steps.map(async step => {
          const ref = targets.current.get(step.target);
          const rect = ref ? await measure(ref) : null;
          return rect && inWindow(rect, window) ? { step, rect } : null;
        }),
      )
        .then(measured => {
          const usable = measured.filter((m): m is Measured => m !== null);
          // Nothing to point at: count it seen rather than nag on every visit.
          if (usable.length === 0) finish(id);
          else setActive({ id, steps: usable, index: 0 });
        })
        .finally(() => {
          starting.current = false;
        });
    },
    [active, seen, finish],
  );

  const next = useCallback(() => {
    setActive(current => {
      if (!current) return null;
      if (current.index + 1 >= current.steps.length) {
        finish(current.id);
        return null;
      }
      return { ...current, index: current.index + 1 };
    });
  }, [finish]);

  const skip = useCallback(() => {
    if (active) finish(active.id);
  }, [active, finish]);

  const cancel = useCallback(() => setActive(null), []);

  // An order ringing is never covered by a tip.
  useEffect(() => {
    if (offer && active) setActive(null);
  }, [offer, active]);

  const markIntroSeen = useCallback(() => {
    setSeen(current => {
      if (isSeen(current, INTRO_ID)) return current;
      const next = markSeen(current, INTRO_ID);
      AsyncStorage.setItem(SEEN_KEY, encodeSeen(next)).catch(() => {});
      return next;
    });
  }, []);

  const resetTips = useCallback(() => {
    setActive(null);
    persist(resetAll(seen));
  }, [persist, seen]);

  const value = useMemo(
    () => ({
      loaded,
      seen,
      active,
      register,
      start,
      next,
      skip,
      cancel,
      markIntroSeen,
      resetTips,
    }),
    [
      loaded,
      seen,
      active,
      register,
      start,
      next,
      skip,
      cancel,
      markIntroSeen,
      resetTips,
    ],
  );
  return (
    <GuideContext.Provider value={value}>{children}</GuideContext.Provider>
  );
}

export function useGuide(): GuideContextValue {
  const ctx = useContext(GuideContext);
  if (!ctx) throw new Error('useGuide outside GuideProvider');
  return ctx;
}

/**
 * Wraps a control the guide may point at. `collapsable={false}` keeps the
 * View in Android's native tree so it can be measured; without it the
 * optimiser folds an empty wrapper away and measure returns zeros.
 */
export function GuideTarget({
  id,
  children,
  style,
}: {
  id: TargetId;
  children: React.ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  const { register } = useGuide();
  const ref = useRef<Host | null>(null);
  useEffect(() => register(id, ref), [id, register]);
  return (
    <View ref={ref} collapsable={false} style={style}>
      {children}
    </View>
  );
}
