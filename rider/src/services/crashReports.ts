import { getCrashlytics, log, recordError, setUserId } from '@react-native-firebase/crashlytics';

import { firebaseReady } from './push';

/**
 * Crash reports (Crashlytics), in the same Firebase project as push.
 *
 * Off in debug builds (`firebase.json`), so a red box on the developer's
 * emulator does not page anyone. Every call is guarded like push: without
 * `google-services.json` the app builds and runs with reports simply off.
 * Native crashes and uncaught JS errors are recorded by the library itself;
 * this adds what an error boundary catches, which never reaches it otherwise.
 */
export function reportScreenError(error: Error, componentStack?: string | null): void {
  if (!firebaseReady()) return;
  try {
    const c = getCrashlytics();
    if (componentStack) log(c, componentStack.slice(0, 2000));
    recordError(c, error, 'ScreenError');
  } catch {}
}

/** The rider's user id (never the phone number) so a report can be followed up. */
export function identifyRider(userId: string | null): void {
  if (!firebaseReady()) return;
  try {
    void setUserId(getCrashlytics(), userId ?? '').catch(() => {});
  } catch {}
}
