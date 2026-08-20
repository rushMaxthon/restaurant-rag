import { NativeModules, Platform } from 'react-native';

/**
 * Bundle ID used when the native module is unavailable, which happens only if
 * the app runs a JS bundle newer than the installed native binary. It matches
 * the bundle ID shipped today, so the app still resolves a valid configuration
 * instead of failing to start.
 */
export const FALLBACK_BUNDLE_ID = 'com.quickbite.all';

/** Matches the backend `app_client_platform` enum. */
export type AppPlatform = 'IOS' | 'ANDROID';

export interface AppIdentity {
  bundleId: string;
  platform: AppPlatform;
  /** False when the bundle ID came from the fallback rather than the binary. */
  isNativeBundleId: boolean;
}

interface AppInfoNativeModule {
  bundleId?: string;
  platform?: string;
  getBundleId?: () => Promise<string>;
}

/** Read on each call rather than captured, so late registration still works. */
function getNativeModule(): AppInfoNativeModule | undefined {
  return NativeModules.AppInfo;
}

function readConstant(): string | null {
  const value = getNativeModule()?.bundleId;
  return typeof value === 'string' && value.length > 0 ? value : null;
}

/**
 * Platform reported by the native module, falling back to React Native's own
 * `Platform.OS`. The fallback is reliable on its own, so the platform is
 * correct even when the app info module is missing.
 */
function resolvePlatform(): AppPlatform {
  const reported = getNativeModule()?.platform;
  if (reported === 'IOS' || reported === 'ANDROID') {
    return reported;
  }
  return Platform.OS === 'ios' ? 'IOS' : 'ANDROID';
}

/** Synchronous read of the native bundle ID, or null when it is unavailable. */
export function getNativeBundleId(): string | null {
  return readConstant();
}

/**
 * Resolves the identity this binary was built with: the Android
 * `applicationId` or the iOS `CFBundleIdentifier`, plus the platform.
 * Never rejects.
 */
export async function resolveAppIdentity(): Promise<AppIdentity> {
  const platform = resolvePlatform();

  const fromConstant = readConstant();
  if (fromConstant) {
    if (__DEV__) {
      console.log(`[BundleId] Detected Bundle ID: ${fromConstant}`);
    }
    if (__DEV__) {
      console.log(
        `[BundleId] Source: native module constant | platform: ${platform}`,
      );
    }
    return { bundleId: fromConstant, platform, isNativeBundleId: true };
  }

  try {
    const fromMethod = await getNativeModule()?.getBundleId?.();
    if (typeof fromMethod === 'string' && fromMethod.length > 0) {
      if (__DEV__) {
        console.log(`[BundleId] Detected Bundle ID: ${fromMethod}`);
      }
      if (__DEV__) {
        console.log(
          `[BundleId] Source: native module method | platform: ${platform}`,
        );
      }
      return { bundleId: fromMethod, platform, isNativeBundleId: true };
    }
  } catch (error) {
    console.warn('[BundleId] Native bundle ID lookup failed', error);
  }

  console.warn(
    `[BundleId] Detected Bundle ID: ${FALLBACK_BUNDLE_ID} (FALLBACK - native module unavailable)`,
  );
  console.warn(
    '[BundleId] This is NOT the real bundle ID. Rebuild the native app to pick it up.',
  );
  return { bundleId: FALLBACK_BUNDLE_ID, platform, isNativeBundleId: false };
}

/** Backwards-compatible accessor for callers that only need the bundle ID. */
export async function resolveBundleId(): Promise<string> {
  return (await resolveAppIdentity()).bundleId;
}
