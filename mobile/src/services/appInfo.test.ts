import { NativeModules, Platform } from 'react-native';
import {
  FALLBACK_BUNDLE_ID,
  getNativeBundleId,
  resolveAppIdentity,
  resolveBundleId,
} from './appInfo';

describe('appInfo identity resolution', () => {
  const originalAppInfo = NativeModules.AppInfo;

  afterEach(() => {
    NativeModules.AppInfo = originalAppInfo;
    jest.restoreAllMocks();
  });

  function mockNativeModule(appInfo: unknown) {
    NativeModules.AppInfo = appInfo;
  }

  it('reads bundle ID and platform from the native constants', async () => {
    mockNativeModule({ bundleId: 'com.quickbite.all', platform: 'ANDROID' });
    expect(getNativeBundleId()).toBe('com.quickbite.all');
    await expect(resolveAppIdentity()).resolves.toEqual({
      bundleId: 'com.quickbite.all',
      platform: 'ANDROID',
      isNativeBundleId: true,
    });
  });

  it('picks up a re-branded build without any code change', async () => {
    mockNativeModule({ bundleId: 'com.quickbite.all', platform: 'IOS' });
    const identity = await resolveAppIdentity();
    expect(identity.bundleId).toBe('com.quickbite.all');
    expect(identity.platform).toBe('IOS');
  });

  it('falls back to Platform.OS when the native platform is missing', async () => {
    mockNativeModule({ bundleId: 'com.quickbite.all' });
    const identity = await resolveAppIdentity();
    expect(identity.platform).toBe(Platform.OS === 'ios' ? 'IOS' : 'ANDROID');
  });

  it('ignores an unrecognised native platform value', async () => {
    mockNativeModule({ bundleId: 'com.quickbite.all', platform: 'WINDOWS' });
    const identity = await resolveAppIdentity();
    expect(['IOS', 'ANDROID']).toContain(identity.platform);
  });

  it('falls back to the async method when no constant is exported', async () => {
    mockNativeModule({
      getBundleId: jest.fn().mockResolvedValue('com.quickbite.all'),
    });
    expect(getNativeBundleId()).toBeNull();
    const identity = await resolveAppIdentity();
    expect(identity.bundleId).toBe('com.quickbite.all');
    expect(identity.isNativeBundleId).toBe(true);
  });

  it('flags the fallback when the native module is missing', async () => {
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    mockNativeModule(undefined);
    const identity = await resolveAppIdentity();
    expect(identity.bundleId).toBe(FALLBACK_BUNDLE_ID);
    expect(identity.isNativeBundleId).toBe(false);
    // The platform stays correct even without the native module.
    expect(['IOS', 'ANDROID']).toContain(identity.platform);
  });

  it('falls back when the native method throws', async () => {
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    mockNativeModule({
      getBundleId: jest.fn().mockRejectedValue(new Error('boom')),
    });
    await expect(resolveBundleId()).resolves.toBe(FALLBACK_BUNDLE_ID);
  });

  it('ignores an empty native bundle ID', async () => {
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    mockNativeModule({ bundleId: '', platform: 'IOS' });
    const identity = await resolveAppIdentity();
    expect(identity.bundleId).toBe(FALLBACK_BUNDLE_ID);
    expect(identity.isNativeBundleId).toBe(false);
  });
});
