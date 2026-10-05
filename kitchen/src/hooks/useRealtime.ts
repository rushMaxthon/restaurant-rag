import { useEffect, useMemo, useSyncExternalStore } from 'react';
import { API_BASE_URL } from '@/config/api';
import { ordersChanged } from '@services/orderEvents';
import { RealtimeClient } from '@services/realtime';
import type { BoardScope, RealtimeStatus } from '@/types/app';
import { useAppActions } from '@hooks/useAppStore';

const noSubscription = () => () => undefined;
const noStatus = () => null;

// The board's socket for as long as a session is open. A push only reports
// "orders changed"; usePolling turns that into REST refetches. Null while
// there is nothing to connect.
export function useRealtime(token: string | null, scope: BoardScope): RealtimeStatus | null {
  const { signOut } = useAppActions();

  const client = useMemo(
    () =>
      token
        ? new RealtimeClient({
            apiBaseUrl: API_BASE_URL,
            token,
            onChange: ordersChanged,
            onSignOut: () => signOut({ expired: true }),
          })
        : null,
    [token, signOut],
  );

  // Before `start`, so the first handshake already carries the branch.
  useEffect(() => {
    client?.resubscribe({
      restaurant_id: scope.restaurantId,
      restaurant_location_id: scope.locationId,
    });
  }, [client, scope.restaurantId, scope.locationId]);

  useEffect(() => {
    if (!client) {
      return;
    }
    client.start();
    return () => client.stop();
  }, [client]);

  return useSyncExternalStore(
    client?.subscribe ?? noSubscription,
    client?.getStatus ?? noStatus,
  );
}
