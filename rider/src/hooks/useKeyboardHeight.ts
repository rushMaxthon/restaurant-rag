import { useEffect, useState } from 'react';
import { Keyboard } from 'react-native';

/**
 * How tall the on-screen keyboard is right now (0 when hidden).
 *
 * Needed because Android 15+ apps are edge-to-edge: the window no longer
 * shrinks for the keyboard (`adjustResize` does nothing), so a field near the
 * bottom - the delivery code - ends up under the keys unless the screen makes
 * room itself.
 */
export function useKeyboardHeight(): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const show = Keyboard.addListener('keyboardDidShow', e => setHeight(e.endCoordinates.height));
    const hide = Keyboard.addListener('keyboardDidHide', () => setHeight(0));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  return height;
}
