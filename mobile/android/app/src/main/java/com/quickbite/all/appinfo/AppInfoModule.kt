package com.quickbite.all.appinfo

import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod
import com.facebook.react.module.annotations.ReactModule

/**
 * Exposes the build's own application id to JS so the app can resolve its
 * configuration from the backend without any hardcoded identifier.
 *
 * `packageName` returns the `applicationId` declared in `app/build.gradle`, so
 * changing that value and rebuilding is enough to re-brand the app.
 */
@ReactModule(name = AppInfoModule.NAME)
class AppInfoModule(reactContext: ReactApplicationContext) :
  ReactContextBaseJavaModule(reactContext) {

  override fun getName(): String = NAME

  /** Exported as constants so JS can read them synchronously during startup. */
  override fun getConstants(): MutableMap<String, Any> =
    hashMapOf(
      BUNDLE_ID_KEY to reactApplicationContext.packageName,
      PLATFORM_KEY to PLATFORM_VALUE,
    )

  /** Async accessor, for callers that cannot rely on constants. */
  @ReactMethod
  fun getBundleId(promise: Promise) {
    promise.resolve(reactApplicationContext.packageName)
  }

  companion object {
    const val NAME = "AppInfo"
    private const val BUNDLE_ID_KEY = "bundleId"
    private const val PLATFORM_KEY = "platform"

    /** Matches the backend `app_client_platform` enum. */
    private const val PLATFORM_VALUE = "ANDROID"
  }
}
