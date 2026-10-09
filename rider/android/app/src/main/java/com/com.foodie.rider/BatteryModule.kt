package com.foodie.rider

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
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
