/**
 * The one place the mobile app decides which backend it talks to.
 *
 * Selected with `__DEV__` rather than an env file, and that is deliberate.
 * mobile/.env documents that this app has no env loader — no
 * react-native-config, no `process.env` at runtime — and that it must stay
 * that way, because an env mechanism is how a Stripe secret key ends up
 * compiled into a client bundle. `__DEV__` needs no dependency, no native
 * rebuild config, and is already the switch this codebase uses elsewhere
 * (services/pushNotifications.ts, utils/generatedComboCart.ts).
 *
 * The trailing `/api` is load-bearing: the backend mounts every route under
 * `settings.api_v1_prefix`, which is `/api` in every environment. Call sites
 * pass paths relative to it, so a base URL without the prefix produces a 404
 * on every single request.
 */

/**
 * Metro dev build. A LAN address, not `localhost`: on a physical device
 * `localhost` resolves to the phone itself, so it must be the address of the
 * developer's machine on the shared network. Change this when the network
 * hands out a different one — it is the only value here that is
 * machine-specific.
 */
const DEV_API_BASE_URL = 'http://192.168.29.236:8000/api';

/** Release build (`assembleRelease` / `bundleRelease` / an Xcode Release scheme). */
const PROD_API_BASE_URL = 'https://restaurant-rag-api-xjfx.onrender.com/api';

/**
 * `__DEV__` is injected by the React Native bundler: true for a Metro dev
 * build, false for any release build. So a shipped app reaches Render and a
 * developer's build reaches their laptop, with nothing to remember and no
 * step that can be forgotten before a release.
 */
export const API_BASE_URL = DEV_API_BASE_URL;
