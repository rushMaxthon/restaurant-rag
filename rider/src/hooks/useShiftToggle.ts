import { useCallback, useRef, useState } from 'react';

import { usePermissions } from '@hooks/usePermissions';
import { useNav } from '@navigation/types';
import { ApiError } from '@/services/http';
import { useRider } from '@/store/RiderProvider';
import { useApi } from '@/store/SessionProvider';
import { translate } from '@/i18n/translate';
import { haptic } from '@utils/haptics';
import { firstMissing } from '@utils/permissions';

/**
 * Going on and off shift, for Home and the Orders tab alike: an offline rider
 * looking at the board should not have to go back to Home to take an order.
 * One place asks the phone for permissions at the tap and words the failure.
 */
export function useShiftToggle() {
  const api = useApi();
  const nav = useNav();
  const { me, setMe } = useRider();
  const permissions = usePermissions();
  const refreshPermissions = permissions.refresh;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A ref, set before the first await: `busy` is state and only flips after
  // the permission check, so a double tap could open Permissions twice or
  // send two status changes.
  const inFlight = useRef(false);

  const toggle = useCallback(
    async (next: boolean) => {
      if (inFlight.current) return;
      inFlight.current = true;
      try {
        // Asked again at the tap: a copy read when the screen opened would
        // send a rider who has since granted everything back to Permissions
        // in a loop.
        if (next && firstMissing(await refreshPermissions()) !== null) {
          nav.navigate('Permissions');
          return;
        }
        setBusy(true);
        setError(null);
        setMe(await api.setOnline(next));
      } catch (e) {
        haptic('error');
        setError(
          e instanceof ApiError
            ? e.message
            : translate('system.statusFailed'),
        );
      } finally {
        inFlight.current = false;
        setBusy(false);
      }
    },
    [api, nav, refreshPermissions, setMe],
  );

  return {
    online: me?.status === 'ONLINE' || me?.status === 'ON_TRIP',
    toggle,
    busy,
    error,
    disabledReason:
      me?.status === 'ON_TRIP'
        ? translate('system.finishToGoOffline')
        : null,
  };
}
