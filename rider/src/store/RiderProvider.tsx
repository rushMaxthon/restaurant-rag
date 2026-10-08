import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { AppState, type AppStateStatus } from 'react-native';

import { ApiError } from '@/services/http';
import { useApi } from '@/store/SessionProvider';
import type { Offer, RiderMe, Trip } from '@/types/api';

/**
 * What the rider app knows about the rider right now: who they are, whether
 * they are online, the offer on their screen and the trip in their hands.
 *
 * REST is the only source of truth; this polls it at the rate the moment
 * needs - every 3 s for offers while online and idle (an offer lasts 30 s),
 * every 15 s for a trip, 30 s for the profile - and refetches the moment the
 * app comes back to the foreground. Until push is set up (Firebase), the
 * offer poll is what brings a new order in.
 */

const OFFER_POLL_MS = 3_000;
const TRIP_POLL_MS = 15_000;
const ME_POLL_MS = 30_000;

type RiderContextValue = {
  me: RiderMe | null;
  trip: Trip | null;
  offer: Offer | null;
  loading: boolean;
  error: string | null;
  refreshMe: () => Promise<void>;
  refreshTrip: () => Promise<void>;
  refreshOffer: () => Promise<void>;
  setMe: (me: RiderMe) => void;
  setTrip: (trip: Trip | null) => void;
  clearOffer: () => void;
};

const RiderContext = createContext<RiderContextValue | null>(null);

function useForeground(): boolean {
  const [active, setActive] = useState(AppState.currentState === 'active');
  useEffect(() => {
    const sub = AppState.addEventListener('change', (next: AppStateStatus) => setActive(next === 'active'));
    return () => sub.remove();
  }, []);
  return active;
}

export function RiderProvider({ children }: { children: React.ReactNode }) {
  const api = useApi();
  const foreground = useForeground();
  const [me, setMe] = useState<RiderMe | null>(null);
  const [trip, setTrip] = useState<Trip | null>(null);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const dismissed = useRef<Set<string>>(new Set());

  const refreshMe = useCallback(async () => {
    try {
      setMe(await api.me());
      setError(null);
    } catch (e) {
      if (e instanceof ApiError) setError(e.message);
    }
  }, [api]);

  const refreshTrip = useCallback(async () => {
    try {
      setTrip((await api.trip()) ?? null);
    } catch (e) {
      if (e instanceof ApiError && !e.isNetwork) setError(e.message);
    }
  }, [api]);

  const refreshOffer = useCallback(async () => {
    try {
      const next = (await api.currentOffer()) ?? null;
      setOffer(next && !dismissed.current.has(next.id) ? next : null);
    } catch {
      // an offer poll that fails is simply tried again in 3 s
    }
  }, [api]);

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
    Promise.all([refreshMe(), refreshTrip()]).finally(() => alive && setLoading(false));
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

  const wantsOffers = foreground && me?.status === 'ONLINE' && !trip;
  useEffect(() => {
    if (!wantsOffers) {
      setOffer(null);
      return;
    }
    void refreshOffer();
    const id = setInterval(refreshOffer, OFFER_POLL_MS);
    return () => clearInterval(id);
  }, [wantsOffers, refreshOffer]);

  const value = useMemo(
    () => ({ me, trip, offer, loading, error, refreshMe, refreshTrip, refreshOffer, setMe, setTrip, clearOffer }),
    [me, trip, offer, loading, error, refreshMe, refreshTrip, refreshOffer, clearOffer],
  );
  return <RiderContext.Provider value={value}>{children}</RiderContext.Provider>;
}

export function useRider(): RiderContextValue {
  const ctx = useContext(RiderContext);
  if (!ctx) throw new Error('useRider outside RiderProvider');
  return ctx;
}
