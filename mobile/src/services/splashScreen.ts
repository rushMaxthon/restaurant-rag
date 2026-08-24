import { NativeModules } from 'react-native';

/**
 * Dismisses the native splash screen shown by MainActivity.kt (Android) and
 * AppDelegate.swift (iOS) before the JS bundle has rendered anything.
 *
 * Call once, when the app has something real to show - AppNavigator does this
 * exactly when `bootstrapped` flips true, not on first mount. Hiding earlier
 * would swap the native splash for AppNavigator's own loading spinner, which
 * defeats the point of a splash screen: covering that exact gap.
 *
 * Reads `NativeModules.SplashScreen` directly - the same module
 * react-native-splash-screen's own `index.js` exports as its default -
 * rather than importing the package, so the type here is honestly
 * `| undefined` instead of trusting the package's non-nullable declared
 * type. It IS genuinely undefined whenever the native side was never linked:
 * a stale binary running a newer JS bundle, or a test environment with no
 * native modules at all. Read on each call rather than captured at import
 * time, so a late-registering module still works - matching
 * services/appInfo.ts's `getNativeModule()`.
 */
interface SplashScreenNativeModule {
  hide?: () => void;
  show?: () => void;
}

function getNativeModule(): SplashScreenNativeModule | undefined {
  return NativeModules.SplashScreen;
}

export function hideSplashScreen(): void {
  try {
    getNativeModule()?.hide?.();
  } catch (error) {
    console.warn('[SplashScreen] hide() failed', error);
  }
}
