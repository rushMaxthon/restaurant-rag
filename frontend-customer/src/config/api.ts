/**
 * The one place the customer app decides which backend it talks to.
 *
 * Every request goes through `API_BASE_URL` in services/api.ts — both the
 * plain `request()` helper and the chat streaming call — so a deployment is
 * retargeted by changing this file or the env var below, never by editing a
 * call site.
 *
 * The trailing `/api` is load-bearing: the backend mounts every route under
 * `settings.api_v1_prefix`, which is `/api` in every environment. Call sites
 * pass paths relative to it (`/restaurants`, `/auth/login`), so a base URL
 * without the prefix produces a 404 on every single request.
 */

/** `vite dev`. The backend running on the developer's own machine. */
const DEV_API_BASE_URL = 'http://localhost:8000/api';

/** `vite build`. The Render web service. */
const PROD_API_BASE_URL = 'https://restaurant-rag-api-xjfx.onrender.com/api';

/**
 * `import.meta.env.PROD` is set by Vite itself — false under `vite dev`, true
 * for `vite build` — so the correct backend is chosen by which command ran,
 * with no dashboard configuration involved.
 *
 * That default is deliberate rather than lazy. Selecting the production URL
 * only from an env var means a missing or misspelled Vercel variable silently
 * ships a bundle pointing at `http://localhost:8000`, which fails for every
 * user while building and deploying perfectly green. Baking the fallback in
 * makes the correct URL the thing that happens when nobody configures
 * anything.
 *
 * `VITE_API_BASE_URL` still wins when set, which is what a preview build
 * against a staging backend, or a phone testing against a LAN dev server,
 * needs. Vite inlines it at BUILD time, so changing it requires a rebuild.
 */
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.PROD ? PROD_API_BASE_URL : DEV_API_BASE_URL);
