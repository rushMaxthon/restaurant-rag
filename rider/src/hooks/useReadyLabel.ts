import { useEffect, useState } from 'react';

import { useI18n } from '@/i18n';
import { readyLabel } from '@utils/ready';

/**
 * `readyLabel`, kept current: "in 18 min" must count down while the screen
 * sits open, not only when the next poll happens to redraw it. Ticks every
 * 20 s, and only while there is a ready time to show.
 */
export function useReadyLabel(readyAt: string | null | undefined): string | null {
  // Subscribes to the language, so a switch in Profile redraws the label.
  useI18n();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!readyAt) return;
    setNow(new Date());
    const timer = setInterval(() => setNow(new Date()), 20_000);
    return () => clearInterval(timer);
  }, [readyAt]);
  return readyLabel(readyAt, now);
}
