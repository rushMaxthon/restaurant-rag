package com.quickbite.bangkokbowl

import android.os.Bundle
import com.facebook.react.ReactActivity
import com.facebook.react.ReactActivityDelegate
import com.facebook.react.defaults.DefaultNewArchitectureEntryPoint.fabricEnabled
import com.facebook.react.defaults.DefaultReactActivityDelegate
import org.devio.rn.splashscreen.SplashScreen

class MainActivity : ReactActivity() {

  /**
   * Returns the name of the main component registered from JavaScript. This is used to schedule
   * rendering of the component.
   */
  override fun getMainComponentName(): String = "mobile"

  /**
   * Returns the instance of the [ReactActivityDelegate]. We use [DefaultReactActivityDelegate]
   * which allows you to enable New Architecture with a single boolean flags [fabricEnabled]
   */
  override fun createReactActivityDelegate(): ReactActivityDelegate =
      DefaultReactActivityDelegate(this, mainComponentName, fabricEnabled)

  override fun onCreate(savedInstanceState: Bundle?) {
    // Must run before super.onCreate - it shows a Dialog (res/layout/launch_screen.xml)
    // that stays on top until JS calls SplashScreen.hide() from
    // src/services/splashScreen.ts, bridging the gap between the OS-drawn
    // cold-start frame and the app's first rendered screen.
    SplashScreen.show(this)
    // Passed as null rather than the real savedInstanceState: this library's
    // own README calls this out as required to avoid a crash on restore when
    // react-native-screens is also installed (this app uses it via React
    // Navigation's native-stack).
    super.onCreate(null)
  }
}
