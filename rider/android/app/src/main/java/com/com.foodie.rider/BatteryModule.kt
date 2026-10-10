package com.foodie.rider

import android.annotation.SuppressLint
import android.app.NotificationManager
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import com.facebook.react.bridge.Promise
import com.facebook.react.bridge.ReactApplicationContext
import com.facebook.react.bridge.ReactContextBaseJavaModule
import com.facebook.react.bridge.ReactMethod

/**
 * Asks Android to stop putting this app to sleep, with the system's own
 * one-tap "Allow" dialog for THIS app.
 *
 * Notifee only opens the general battery list, where a rider has to find the
 * app among dozens and pick the right option - most give up. A delivery app
 * whose core job is ringing for new orders is the case this permission
 * (REQUEST_IGNORE_BATTERY_OPTIMIZATIONS) exists for.
 */
class BatteryModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context) {
  override fun getName() = "RiderBattery"

  @ReactMethod
  fun isUnrestricted(promise: Promise) {
    val power = context.getSystemService(PowerManager::class.java)
    promise.resolve(power?.isIgnoringBatteryOptimizations(context.packageName) ?: true)
  }

  /**
   * Android 14 stopped granting full-screen notifications to apps that are not
   * a phone or an alarm clock. Without it an offer cannot light up a locked
   * phone - it arrives as a quiet line in the shade. Older Android: always.
   */
  @ReactMethod
  fun canUseFullScreen(promise: Promise) {
    if (Build.VERSION.SDK_INT < 34) {
      promise.resolve(true)
      return
    }
    val manager = context.getSystemService(NotificationManager::class.java)
    promise.resolve(manager?.canUseFullScreenIntent() ?: true)
  }

  @ReactMethod
  fun openFullScreenSettings(promise: Promise) {
    if (Build.VERSION.SDK_INT < 34) {
      promise.resolve(false)
      return
    }
    try {
      val intent = Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT)
        .setData(Uri.parse("package:${context.packageName}"))
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      context.startActivity(intent)
      promise.resolve(true)
    } catch (e: Exception) {
      promise.resolve(false)
    }
  }

  @SuppressLint("BatteryLife")
  @ReactMethod
  fun requestUnrestricted(promise: Promise) {
    try {
      val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
        .setData(Uri.parse("package:${context.packageName}"))
        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
      context.startActivity(intent)
      promise.resolve(true)
    } catch (e: Exception) {
      promise.resolve(false)
    }
  }
}
