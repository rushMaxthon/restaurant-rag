import React, { useEffect, useRef, useState } from 'react';

import { rupees } from '@utils/format';
import { AppText, type AppTextProps } from './AppText';

/**
 * A rupee amount that counts up to its new value (ease-out, ~700 ms).
 * Earnings that grow in front of the rider feel earned; a number that
 * snaps reads as a refresh.
 */
export function AnimatedAmount({ value, duration = 700, ...text }: AppTextProps & { value: number; duration?: number }) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);

  useEffect(() => {
    const start = from.current;
    const delta = value - start;
    if (delta === 0) return;
    const began = Date.now();
    let frame = 0;
    const tick = () => {
      const t = Math.min(1, (Date.now() - began) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(start + delta * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
      else {
        setShown(value);
        from.current = value;
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);

  return (
    <AppText variant="money" {...text}>
      {/* whole rupees while counting, the exact amount (paise too) once it lands */}
      {rupees(shown === value ? value : Math.round(shown))}
    </AppText>
  );
}
