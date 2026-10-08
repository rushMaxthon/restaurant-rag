import HapticFeedback from 'react-native-haptic-feedback';

/**
 * One place that decides what each moment feels like, so the slide, the
 * toggle and the offer alert stay consistent. Never throws: a phone without a
 * vibration motor must not lose a delivery over a missing buzz.
 */
const MAP = {
  light: 'impactLight',
  medium: 'impactMedium',
  heavy: 'impactHeavy',
  success: 'notificationSuccess',
  warning: 'notificationWarning',
  error: 'notificationError',
  tick: 'selection',
} as const;

export type HapticKind = keyof typeof MAP;

export function haptic(kind: HapticKind): void {
  try {
    HapticFeedback.trigger(MAP[kind], { enableVibrateFallback: false, ignoreAndroidSystemSettings: false });
  } catch {
    // no motor, or the native module is missing in a test: nothing to do
  }
}
