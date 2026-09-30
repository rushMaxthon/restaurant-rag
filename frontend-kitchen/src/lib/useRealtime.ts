/**
 * The board's socket, as a hook: connect while signed in, follow the branch.
 *
 * All of the behaviour lives in `RealtimeClient`; this only ties its lifetime
 * to the session and turns a push into "refetch the columns". Status is read
 * with `useSyncExternalStore` because it changes in socket callbacks, outside
 * React — the store, not an effect, is what keeps a render in step with it.
 */

import { useEffect, useMemo, useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { API_BASE_URL } from './api'
import type { BoardScope } from './queries'
import { RealtimeClient, type RealtimeStatus } from './realtime'

const noSubscription = () => () => {}

/** `null` while signed out: nothing to connect, and nothing to show. */
export function useRealtimeBoard(
  token: string | null,
  scope: BoardScope,
  onSignOut: () => void,
): RealtimeStatus | null {
  const queryClient = useQueryClient()

  const client = useMemo(
    () =>
      token
        ? new RealtimeClient({
            apiBaseUrl: API_BASE_URL,
            auth: () => ({ token }),
            onChange: () => void queryClient.invalidateQueries({ queryKey: ['orders'] }),
            onSignOut,
          })
        : null,
    [token, queryClient, onSignOut],
  )

  // Declared before `start` so the first handshake already carries the branch:
  // effects run in declaration order. After that, a branch change moves the
  // open socket via `subscribe`, validated by the server's scope rule.
  useEffect(() => {
    client?.resubscribe({
      restaurant_id: scope.restaurantId,
      restaurant_location_id: scope.locationId,
    })
  }, [client, scope.restaurantId, scope.locationId])

  useEffect(() => {
    if (!client) return
    client.start()
    return () => client.stop()
  }, [client])

  return useSyncExternalStore(
    client?.subscribe ?? noSubscription,
    client?.getStatus ?? (() => null),
  )
}
