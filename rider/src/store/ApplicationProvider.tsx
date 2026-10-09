import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import { ApiError } from '@/services/http';
import { useRider } from '@/store/RiderProvider';
import { useApi } from '@/store/SessionProvider';
import type { ApplicationView } from '@/types/api';
import { sequencer } from '@utils/latest';

type ApplicationContextValue = {
  view: ApplicationView | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  /** Every save, upload and submit answers with the whole application: it replaces ours. */
  setView: (view: ApplicationView) => void;
};

const ApplicationContext = createContext<ApplicationContextValue | null>(null);

/**
 * The rider's application, for the screens a pending rider sees. The server
 * holds it all - there is no draft on the phone - so a second phone, a
 * reinstall or a killed app all open on the same answer. Refetched when the
 * server says it changed (a push or `rider:application`), which is how a
 * send-back reaches a rider looking at the screen.
 */
export function ApplicationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const api = useApi();
  const { applicationTick, me, refreshMe } = useRider();
  const [view, setViewState] = useState<ApplicationView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // A slow GET must not land over the answer a save just gave.
  const [seq] = useState(sequencer);

  const setView = useCallback(
    (next: ApplicationView) => {
      seq.invalidate();
      setViewState(next);
      setError(null);
    },
    [seq],
  );

  const refresh = useCallback(async () => {
    const ticket = seq.start();
    try {
      const next = await api.application();
      if (!seq.isLatest(ticket)) return;
      setViewState(next);
      setError(null);
    } catch (e) {
      if (seq.isLatest(ticket))
        setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [api, seq]);

  useEffect(() => {
    void refresh();
  }, [refresh, applicationTick]);

  // The application says approved before /me does (it is fetched more often
  // here): ask /me now, and RootNavigator swaps in the tabs.
  const approved = view?.status === 'APPROVED';
  useEffect(() => {
    if (approved && me?.onboarding !== 'APPROVED') void refreshMe();
  }, [approved, me?.onboarding, refreshMe]);

  const value = useMemo(
    () => ({ view, loading, error, refresh, setView }),
    [view, loading, error, refresh, setView],
  );
  return (
    <ApplicationContext.Provider value={value}>
      {children}
    </ApplicationContext.Provider>
  );
}

export function useApplication(): ApplicationContextValue {
  const ctx = useContext(ApplicationContext);
  if (!ctx) throw new Error('useApplication outside ApplicationProvider');
  return ctx;
}
