import { useEffect, useRef } from 'react';
import { onOrdersChanged } from '@services/orderEvents';
import { useAppForegroundEffect } from '@hooks/useAppForegroundEffect';

// Runs `refresh` now, every `intervalMs`, when the app comes back to the
// foreground, and whenever orders are reported changed. Every order screen
// stays current through this one hook, so they cannot disagree about when.
//
// A NEW `refresh` (callers memoise it on what it fetches — branch, search)
// runs immediately and restarts the interval. Keying only on the interval
// left a branch switch or a search waiting up to a full poll to take effect.
export function usePolling(
  refresh: () => void,
  intervalMs: number,
  enabled: boolean,
): void {
  const latest = useRef(refresh);
  latest.current = refresh;

  useEffect(() => {
    if (!enabled) {
      return;
    }
    latest.current();
    const timer = setInterval(() => latest.current(), intervalMs);
    const unsubscribe = onOrdersChanged(() => latest.current());
    return () => {
      clearInterval(timer);
      unsubscribe();
    };
  }, [enabled, intervalMs, refresh]);

  useAppForegroundEffect(() => {
    if (enabled) {
      latest.current();
    }
  });
}
