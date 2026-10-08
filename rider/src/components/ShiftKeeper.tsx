import React, { createContext, useContext, useEffect } from 'react';

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

  return (
    <LocationContext.Provider value={{ ...location, permitted }}>
      {children}
    </LocationContext.Provider>
  );
}

export function useRiderLocation() {
  return useContext(LocationContext);
}
