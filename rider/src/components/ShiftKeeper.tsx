import React, { createContext, useContext, useEffect, useMemo } from 'react';

import {
  useLocationReporter,
  type LocationState,
} from '@hooks/useLocationReporter';
import { usePermissions } from '@hooks/usePermissions';
import { startShift, stopShift } from '@/services/shiftService';
import { useRider } from '@/store/RiderProvider';

const LocationContext = createContext<LocationState & { permitted: boolean }>({
  lastFix: null,
  error: null,
  permitted: false,
});

/**
 * The GPS's trouble alone, for screens that only warn about it (Home): they
 * must not re-render on every fix, which comes every 3-5 s on the move.
 */
const LocationErrorContext = createContext<string | null>(null);

/**
 * Owns the rider's shift for the whole signed-in app, whichever screen is
 * open: the GPS watch and the location reports (was on Home, so it depended
 * on Home staying mounted), and the foreground service that keeps both
 * running in the background. Screens read the latest position from here.
 */
export function ShiftKeeper({ children }: { children: React.ReactNode }) {
  const { me } = useRider();
  const permissions = usePermissions();
  const permitted = permissions.state?.location ?? false;
  const location = useLocationReporter(me?.status, permitted);
  const mode =
    me?.status === 'ON_TRIP'
      ? 'trip'
      : me?.status === 'ONLINE'
      ? 'online'
      : null;

  useEffect(() => {
    if (mode && permitted) {
      void startShift(mode);
    } else {
      void stopShift();
    }
  }, [mode, permitted]);

  // Signing out unmounts this: the service must not outlive the session.
  useEffect(() => () => void stopShift(), []);

  const { lastFix, error } = location;
  const value = useMemo(
    () => ({ lastFix, error, permitted }),
    [lastFix, error, permitted],
  );
  return (
    <LocationContext.Provider value={value}>
      <LocationErrorContext.Provider value={error}>
        {children}
      </LocationErrorContext.Provider>
    </LocationContext.Provider>
  );
}

/** The latest fix too: re-renders with every one (the trip's distance label). */
export function useRiderLocation() {
  return useContext(LocationContext);
}

/** Only why the GPS is not working, or null. */
export function useLocationError() {
  return useContext(LocationErrorContext);
}
