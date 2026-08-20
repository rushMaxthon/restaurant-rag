import {useEffect, useRef} from 'react';
import {AppState, type AppStateStatus} from 'react-native';

export function useAppForegroundEffect(
  callback: () => void,
  enabled: boolean = true,
): void {
  const callbackRef = useRef(callback);

  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let currentState: AppStateStatus = AppState.currentState;
    const subscription = AppState.addEventListener('change', nextState => {
      const becameActive =
        (currentState === 'background' || currentState === 'inactive') &&
        nextState === 'active';
      currentState = nextState;
      if (becameActive) {
        callbackRef.current();
      }
    });

    return () => {
      subscription.remove();
    };
  }, [enabled]);
}
