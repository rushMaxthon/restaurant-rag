import { useEffect, useState } from 'react';

// The current time, re-read every `intervalMs`. Wait times read in whole
// minutes, so ticking every second would re-render the board to change
// nothing — but a minute is too slow, a ticket would sit at the wrong urgency.
export function useNow(intervalMs = 15000): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
