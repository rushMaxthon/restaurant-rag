import UIKit
import React
import React_RCTAppDelegate
import ReactAppDependencyProvider
import FirebaseCore
// Available without a bridging header because the Podfile sets
// `use_frameworks! :linkage => :static` - CocoaPods builds this Objective-C
// pod as a proper Swift-importable framework module (see
// Pods/Target Support Files/react-native-splash-screen/*.modulemap).
import react_native_splash_screen

@main
class AppDelegate: UIResponder, UIApplicationDelegate {
  var window: UIWindow?

  var reactNativeDelegate: ReactNativeDelegate?
  var reactNativeFactory: RCTReactNativeFactory?

  func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
  ) -> Bool {
    if FirebaseApp.app() == nil {
      FirebaseApp.configure()
    }

    let delegate = ReactNativeDelegate()
    let factory = RCTReactNativeFactory(delegate: delegate)
    delegate.dependencyProvider = RCTAppDependencyProvider()

    reactNativeDelegate = delegate
    reactNativeFactory = factory

    window = UIWindow(frame: UIScreen.main.bounds)

    factory.startReactNative(
      withModuleName: "mobile",
      in: window,
      launchOptions: launchOptions
    )

    // Keeps LaunchScreen.storyboard's artwork on screen past the moment iOS
    // would otherwise tear it down, until JS calls SplashScreen.hide() from
    // src/services/splashScreen.ts. RNSplashScreen.show() blocks by pumping
    // the run loop rather than actually stalling the thread, so React
    // Native's own startup - already under way above - keeps running; it
    // returns as soon as hide() flips the flag it's waiting on.
    RNSplashScreen.show()

    return true
  }
}

class ReactNativeDelegate: RCTDefaultReactNativeFactoryDelegate {
  override func sourceURL(for bridge: RCTBridge) -> URL? {
    self.bundleURL()
  }

  override func bundleURL() -> URL? {
#if DEBUG
    RCTBundleURLProvider.sharedSettings().jsBundleURL(forBundleRoot: "index")
#else
    Bundle.main.url(forResource: "main", withExtension: "jsbundle")
#endif
  }
}
