package com.foodie.rider

import android.app.KeyguardManager
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.view.WindowManager
import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import com.facebook.react.defaults.DefaultReactActivityDelegate

class MainActivity : ReactActivity() {

  /**
   * Returns the name of the main component registered from JavaScript. This is used to schedule
   * rendering of the component.
   */
  override fun getMainComponentName(): String = "Rider"

  /**
   * Returns the instance of the [ReactActivityDelegate]. We use [DefaultReactActivityDelegate]
   * which allows you to enable New Architecture with a single boolean flags [fabricEnabled]
   */
  override fun createReactActivityDelegate(): ReactActivityDelegate =
      DefaultReactActivityDelegate(this, mainComponentName, fabricEnabled)

  override fun onCreate(savedInstanceState: Bundle?) {
    wakeForOffer()
    super.onCreate(savedInstanceState)
  }

  override fun onNewIntent(intent: Intent) {
    wakeForOffer()
    super.onNewIntent(intent)
  }

  override fun onStop() {
    super.onStop()
    // Only for the launch that needed it: left on, pressing power on a phone
    // that was showing the app would show it again without unlocking.
    overLock(false)
  }

  /**
   * An offer's full-screen alert opens this screen on a locked phone, or one
   * whose screen is off - nothing else can start it there. Without these two
   * the alert fired and the phone stayed dark in the rider's pocket (found on
   * the emulator, 2026-10-10).
   */
  private fun wakeForOffer() {
    val locked = getSystemService(KeyguardManager::class.java)?.isKeyguardLocked ?: false
    val dark = getSystemService(PowerManager::class.java)?.isInteractive == false
    if (locked || dark) overLock(true)
  }

  @Suppress("DEPRECATION")
  private fun overLock(on: Boolean) {
    if (Build.VERSION.SDK_INT >= 27) {
      setShowWhenLocked(on)
      setTurnScreenOn(on)
      return
    }
    // Android 7-8.0 (minSdk 24): the window flags these methods replaced.
    val flags = WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
    if (on) window.addFlags(flags) else window.clearFlags(flags)
  }
}
