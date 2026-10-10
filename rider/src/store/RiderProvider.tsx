import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { AppState, type AppStateStatus } from 'react-native';

import { keepIfSame } from '@utils/keepIfSame';
import { sequencer } from '@utils/latest';
import { ApiError } from '@/services/http';
import { useRiderRealtime } from '@hooks/useRiderRealtime';
import { useApi, useSession } from '@/store/SessionProvider';
import { canWork } from '@utils/onboarding';
import { offerPollMs } from '@utils/realtime';
import { rememberOnboarding } from '@/services/onboardingMemory';
import { clearOfferAlert, showOfferAlert } from '@/services/push';
import type { Offer, OpenOrder, RiderMe, Trip } from '@/types/api';
import { translate } from '@/i18n/translate';

/**
 * What the rider app knows about the rider right now: who they are, whether
 * they are online, the offer on their screen and the trip in their hands.
 *
 * REST is the only source of truth; this polls it at the rate the moment
 * needs - every 3 s for offers while online and idle (an offer lasts 30 s),
 * every 15 s for a trip, 30 s for the profile - and refetches the moment the
 * app comes back to the foreground. With the live socket up, a push makes
 * it refetch at once and the offer poll drops to a 20 s safety net.
 */

const TRIP_POLL_MS = 15_000;
const ME_POLL_MS = 30_000;
/** The Orders board: often enough that a card a few seconds old is rarely gone. */
const BOARD_POLL_MS = 8_000;

type RiderContextValue = {
  me: RiderMe | null;
  trip: Trip | null;
  offer: Offer | null;
  /** The Orders board - shared by the tab, its badge and Home. */
  openOrders: OpenOrder[];
  loading: boolean;
  error: string | null;
  refreshMe: () => Promise<void>;
  refreshTrip: () => Promise<void>;
  refreshOffer: () => Promise<void>;
  refreshOpenOrders: () => Promise<void>;
  setMe: (me: RiderMe) => void;
  setTrip: (trip: Trip | null) => void;
  clearOffer: () => void;
  /**
   * Goes up whenever the server says the rider's application changed (a push
   * or the socket), so the application screens refetch it.
   */
  applicationTick: number;
  applicationChanged: () => void;
};

const RiderContext = createContext<RiderContextValue | null>(null);

function useForeground(): boolean {
  const [active, setActive] = useState(AppState.currentState === 'active');
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) =>
      setActive(next === 'active'),
    );
    return () => sub.remove();
  }, []);
  return active;
}

export function RiderProvider({ children }: { children: React.ReactNode }) {
  const api = useApi();
  const { state: session, signOut } = useSession();
  const foreground = useForeground();
  const [me, setMeState] = useState<RiderMe | null>(null);
  // Polls, focus refreshes, socket hints and "go online" all write `me`, and
  // the board has as many writers: only the newest answer may land.
  const meSeq = useRef(sequencer()).current;
  const ordersSeq = useRef(sequencer()).current;
  // The trip too: a poll sent before the rider accepted an offer can answer
  // "no trip" after the accept set one, and the trip screen would close.
  const tripSeq = useRef(sequencer()).current;
  const setMe = useCallback(
    (next: RiderMe | null) => {
      meSeq.invalidate();
      setMeState(next);
    },
    [meSeq],
  );
  const [trip, setTripState] = useState<Trip | null>(null);
  const setTrip = useCallback(
    (next: Trip | null) => {
      tripSeq.invalidate();
      setTripState(next);
    },
    [tripSeq],
  );
  const [offer, setOffer] = useState<Offer | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const dismissed = useRef<Set<string>>(new Set());
  const [applicationTick, setApplicationTick] = useState(0);
  // A pending rider is signed in to fill in an application, not to work: the
  // Orders board is not fetched for them (the server would answer an empty
  // list anyway), and ShiftKeeper is not even mounted (RootNavigator).
  const working = canWork(me);

  const refreshMe = useCallback(async () => {
    const ticket = meSeq.start();
    try {
      const next = await api.me();
      if (!meSeq.isLatest(ticket)) return;
      // Unchanged answers keep the old object: a new one re-renders every
      // screen that reads this provider, background tabs included.
      setMeState(prev => keepIfSame(prev, next));
      setError(null);
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    }
  }, [api, meSeq]);

  const refreshTrip = useCallback(async () => {
    try {
      const ticket = tripSeq.start();
      const next = (await api.trip()) ?? null;
      if (!tripSeq.isLatest(ticket)) return;
      setTripState(prev => keepIfSame(prev, next));
    } catch (e) {
      if (e instanceof ApiError && !e.isNetwork) setError(e.message);
    }
  }, [api, tripSeq]);

  const offerSeq = useRef(sequencer()).current;
  const offerOut = useRef(0);
  const refreshOffer = useCallback(async () => {
    const ticket = offerSeq.start();
    offerOut.current += 1;
    try {
      const next = (await api.currentOffer()) ?? null;
      if (!offerSeq.isLatest(ticket)) return;
      const shown = next && !dismissed.current.has(next.id) ? next : null;
      setOffer(prev => keepIfSame(prev, shown));
    } catch {
      // an offer poll that fails is simply tried again on the next tick
    } finally {
      offerOut.current -= 1;
    }
  }, [api, offerSeq]);
  // The timer skips a tick while one is still out: offline, a 3 s poll
  // against a 15 s timeout stacked five requests. A socket hint never waits.
  const pollOffer = useCallback(() => {
    if (offerOut.current === 0) void refreshOffer();
  }, [refreshOffer]);

  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const refreshOpenOrders = useCallback(async () => {
    const ticket = ordersSeq.start();
    try {
      const next = await api.openOrders();
      if (ordersSeq.isLatest(ticket))
        setOpenOrders(prev => keepIfSame(prev, next));
    } catch {
      // the next poll tries again
    }
  }, [api, ordersSeq]);

  const applicationChanged = useCallback(() => {
    setApplicationTick(n => n + 1);
    void refreshMe();
  }, [refreshMe]);

  // Remembered so the next cold start picks tabs or the application without
  // waiting for the network (`gateFor`).
  const onboarding = me?.onboarding ?? null;
  useEffect(() => {
    if (onboarding) void rememberOnboarding(onboarding);
  }, [onboarding]);

  const clearOffer = useCallback(() => {
    setOffer(current => {
      if (current) dismissed.current.add(current.id);
      return null;
    });
  }, []);

  // First load, and again whenever the app returns to the foreground.
  useEffect(() => {
    if (!foreground) return;
    let alive = true;
    Promise.all([refreshMe(), refreshTrip()]).finally(
      () => alive && setLoading(false),
    );
    return () => {
      alive = false;
    };
  }, [foreground, refreshMe, refreshTrip]);

  useEffect(() => {
    if (!foreground) return;
    const id = setInterval(refreshMe, ME_POLL_MS);
    return () => clearInterval(id);
  }, [foreground, refreshMe]);

  useEffect(() => {
    if (!foreground || !trip) return;
    const id = setInterval(refreshTrip, TRIP_POLL_MS);
    return () => clearInterval(id);
  }, [foreground, trip, refreshTrip]);

  // On shift the foreground service keeps the app alive in the background,
  // so the socket and the offer check keep running there too. They used to
  // stop with the screen, and a rider navigating in Google Maps never heard
  // an offer at all (2026-10-08).
  const onShift =
    me?.status === 'ONLINE' || me?.status === 'ON_TRIP' || trip !== null;
  const live = useRiderRealtime(
    session.status === 'signedIn' ? session.token : null,
    foreground || onShift,
    {
      // An offer coming or going is also the board changing.
      onOffer: () => {
        void refreshOffer();
        void refreshOpenOrders();
      },
      onTrip: () => {
        void refreshTrip();
        void refreshMe();
        void refreshOpenOrders();
      },
      onReconnect: () => {
        void refreshMe();
        void refreshTrip();
        void refreshOffer();
        void refreshOpenOrders();
      },
      onRevoked: () => void signOut(translate('system.signedOut')),
      onApplication: applicationChanged,
    },
  );

  const wantsOffers = me?.status === 'ONLINE' && !trip;
  useEffect(() => {
    if (!wantsOffers) {
      setOffer(null);
      return;
    }
    void refreshOffer();
    const id = setInterval(pollOffer, offerPollMs(live));
    return () => clearInterval(id);
  }, [wantsOffers, refreshOffer, pollOffer, live]);

  // Not on screen: ring. On screen, OfferWatcher opens the offer itself.
  const alerted = useRef<string | null>(null);
  useEffect(() => {
    if (offer && !foreground && alerted.current !== offer.id) {
      alerted.current = offer.id;
      void showOfferAlert(offer.id, offer.expires_at);
    }
    if (!offer && alerted.current) {
      void clearOfferAlert(alerted.current);
      alerted.current = null;
    }
  }, [offer, foreground]);

  // The board is for looking at any time, so it is kept fresh whenever the
  // app is open - online or not, mid-trip or not.
  useEffect(() => {
    if (!foreground || !working) return;
    void refreshOpenOrders();
    const id = setInterval(refreshOpenOrders, BOARD_POLL_MS);
    return () => clearInterval(id);
  }, [foreground, working, refreshOpenOrders]);

  const value = useMemo(
    () => ({
      me,
      trip,
      offer,
      openOrders,
      loading,
      error,
      refreshMe,
      refreshTrip,
      refreshOffer,
      refreshOpenOrders,
      setMe,
      setTrip,
      clearOffer,
      applicationTick,
      applicationChanged,
    }),
    [
      me,
      trip,
      offer,
      openOrders,
      loading,
      error,
      refreshMe,
      refreshTrip,
      refreshOffer,
      refreshOpenOrders,
      setMe,
      setTrip,
      clearOffer,
      applicationTick,
      applicationChanged,
    ],
  );
  return (
    <RiderContext.Provider value={value}>{children}</RiderContext.Provider>
  );
}

export function useRider(): RiderContextValue {
  const ctx = useContext(RiderContext);
  if (!ctx) throw new Error('useRider outside RiderProvider');
  return ctx;
}
