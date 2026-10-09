/**
 * Opens the customer's socket while they are signed in, and turns a push into
 * a refetch of the order queries it concerns.
 *
 * Browser-only by construction: `auth.ready` is false during SSR and until
 * hydration has read the stored session, and the socket is started from an
 * effect, which never runs on the server.
 */

import { useEffect, useMemo, useSyncExternalStore, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { API_BASE_URL, announceSessionExpired } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { orderQueriesToRefresh } from "@/lib/order-refresh";
import { RealtimeClient } from "@/lib/realtime";
import { RealtimeStatusContext } from "@/lib/realtime-context";

const noSubscription = () => () => {};

export function RealtimeProvider({ children }: { children: ReactNode }) {
  const { token, ready } = useAuth();
  const queryClient = useQueryClient();

  const client = useMemo(
    () =>
      ready && token
        ? new RealtimeClient({
            apiBaseUrl: API_BASE_URL,
            // The storefront's address is its identity: a token is only valid
            // for the app it was issued to, and a browser cannot set the
            // `X-Forwarded-Host` header on a WebSocket handshake.
            auth: () => ({ token, app_host: window.location.host }),
            // The order, its payment and its delivery card (rider steps that
            // do not move the status only show up there): order-refresh.ts.
            onChange: (orderIds) => {
              for (const queryKey of orderQueriesToRefresh(orderIds)) {
                void queryClient.invalidateQueries({ queryKey });
              }
            },
            // The same path a 401 takes: clear the session once, then the
            // auth provider sends them to sign in from wherever they were.
            onSignOut: announceSessionExpired,
          })
        : null,
    [ready, token, queryClient],
  );

  useEffect(() => {
    if (!client) return;
    client.start();
    return () => client.stop();
  }, [client]);

  const status = useSyncExternalStore(
    client?.subscribe ?? noSubscription,
    client?.getStatus ?? (() => null),
    () => null,
  );

  return <RealtimeStatusContext.Provider value={status}>{children}</RealtimeStatusContext.Provider>;
}
