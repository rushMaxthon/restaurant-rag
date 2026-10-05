import { useEffect, useRef } from 'react';
import { AppState } from 'react-native';

// Runs `effect` each time the app returns to the foreground. A wall tablet
// sleeps and wakes all shift; whatever the board showed before it slept is
// stale by the time it wakes.
export function useAppForegroundEffect(effect: () => void): void {
  const latest = useRef(effect);
  latest.current = effect;

  useEffect(() => {
    let previous = AppState.currentState;
    const subscription = AppState.addEventListener('change', next => {
      if (previous.match(/inactive|background/) && next === 'active') {
        latest.current();
      }
      previous = next;
    });
    return () => subscription.remove();
  }, []);
}
