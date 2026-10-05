import { useEffect, useRef, useState } from 'react';
import { playNewOrderAlert, prepareChime } from '@services/sound';
import type { KitchenOrder } from '@/types/app';
import { newlyArrived } from '@utils/board';

// How long an arriving ticket stays highlighted.
const FRESH_FOR_MS = 4000;

// Announces tickets that arrive while the board is open: a chime (if sound is
// on), a vibration, and a highlight on the ticket itself. The FIRST complete
// load is never announced — every ticket is technically new then, and a
// fanfare for a board somebody just opened teaches them to ignore it.
export function useNewOrderAlerts(
  newOrders: readonly KitchenOrder[],
  loading: boolean,
  soundOn: boolean,
  resetKey: string,
): ReadonlySet<string> {
  const seen = useRef<Set<string> | null>(null);
  const [fresh, setFresh] = useState<ReadonlySet<string>>(new Set());
  const soundRef = useRef(soundOn);
  soundRef.current = soundOn;

  useEffect(() => {
    prepareChime();
  }, []);

  // A branch switch is a different board; its tickets are not "arrivals".
  useEffect(() => {
    seen.current = null;
  }, [resetKey]);

  // By value, so a poll that returns the same tickets changes nothing.
  const idsKey = newOrders.map(order => order.id).join(',');

  useEffect(() => {
    if (loading) {
      return;
    }
    const current = new Set(newOrders.map(order => order.id));
    if (seen.current === null) {
      seen.current = current;
      return;
    }
    const arrived = newlyArrived(seen.current, newOrders);
    seen.current = current;
    if (arrived.length === 0) {
      return;
    }
    setFresh(new Set(arrived));
    if (soundRef.current) {
      playNewOrderAlert();
    }
    const timer = setTimeout(() => setFresh(new Set()), FRESH_FOR_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idsKey, loading]);

  return fresh;
}
