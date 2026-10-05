import React, { createContext, useContext } from 'react';
import { useBoardScope, useSession } from '@hooks/useAppStore';
import { useRealtime } from '@hooks/useRealtime';
import type { RealtimeStatus } from '@/types/app';

const RealtimeContext = createContext<RealtimeStatus | null>(null);

// One socket for the whole app, open while signed in to a restaurant. Every
// screen reads its status from here, so the board, the completed list and an
// open order all poll at the same rate and never open a second connection.
export const RealtimeProvider = ({ children }: { children: React.ReactNode }) => {
  const session = useSession();
  const scope = useBoardScope();
  const status = useRealtime(session?.restaurantId ? session.token : null, scope);
  return <RealtimeContext.Provider value={status}>{children}</RealtimeContext.Provider>;
};

export const useRealtimeStatus = (): RealtimeStatus | null => useContext(RealtimeContext);
