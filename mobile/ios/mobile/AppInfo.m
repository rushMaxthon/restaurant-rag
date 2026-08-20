#import <React/RCTBridgeModule.h>

/**
 * Exposes the build's own bundle identifier to JS so the app can resolve its
 * configuration from the backend without any hardcoded identifier.
 *
 * The value comes from PRODUCT_BUNDLE_IDENTIFIER via Info.plist, so changing
 * the bundle identifier and rebuilding is enough to re-brand the app.
 */
@interface AppInfo : NSObject <RCTBridgeModule>
@end

@implementation AppInfo

RCT_EXPORT_MODULE();

+ (BOOL)requiresMainQueueSetup
{
  return NO;
}

/** Exported as constants so JS can read them synchronously during startup. */
- (NSDictionary *)constantsToExport
{
  NSString *bundleId = [[NSBundle mainBundle] bundleIdentifier];
  // "IOS" matches the backend app_client_platform enum.
  return @{@"bundleId" : bundleId ?: @"", @"platform" : @"IOS"};
}

/** Async accessor, for callers that cannot rely on constants. */
RCT_EXPORT_METHOD(getBundleId
                  : (RCTPromiseResolveBlock)resolve reject
                  : (RCTPromiseRejectBlock)reject)
{
  NSString *bundleId = [[NSBundle mainBundle] bundleIdentifier];
  resolve(bundleId ?: @"");
}

@end
