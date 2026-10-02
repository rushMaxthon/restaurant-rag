/**
 * Browser storage keys that belong to ONE restaurant.
 *
 * Five keys held this storefront's state and every one of them was spelled
 * `bangkok-bowl-…` — the sign-in token, the signed-in user, the cart and
 * branch, the chat session, and a guest's dietary preferences. One deployment
 * serves every restaurant on this platform, so those names were one tenant's
 * written into every other tenant's browser: the same literal problem as the
 * page titles and hero copy that `restaurant_storefront.py` exists to have
 * fixed, in the one place nobody looks.
 *
 * **Scoped by host, because the host is what selects the tenant.** The backend
 * resolves which restaurant a request belongs to from the address it arrived
 * on, so the address is the tenancy boundary and the storage should use the
 * same one. It is also the only identifier available SYNCHRONOUSLY: the store
 * reads localStorage while it renders, long before `/app-config` has said
 * which app client this is, so keying on the app key would mean a signed-out
 * flash on every load.
 *
 * In production each restaurant has its own subdomain, so the browser's own
 * origin separation already keeps them apart and this changes nothing
 * practical. It matters in two cases that are not hypothetical: development,
 * where several tenants are reached on one `localhost` origin by changing the
 * host header; and any future arrangement where one origin fronts more than
 * one restaurant. There a shared key means one tenant's JWT is handed to
 * another's API — the server refuses it, having checked the token's app
 * client, so nothing leaks; but the customer gets a storefront that looks
 * signed in and 401s on everything it tries.
 *
 * **Existing customers keep their carts.** A rename alone would sign everybody
 * out and empty every cart on the deploy. The first read of a key adopts the
 * legacy value if the new one is absent, writes it under the new name and
 * removes the old — once, invisibly.
 */

/** Everything this app stores, named once. */
export const STORAGE = {
  token: "token",
  user: "user",
  state: "state",
  chatSession: "chat-session",
  guestPrefs: "guest-prefs",
} as const;

export type StorageName = (typeof STORAGE)[keyof typeof STORAGE];

/** What each key used to be called, for the one-time adoption below. */
const LEGACY: Record<StorageName, string> = {
  token: "bangkok-bowl-token",
  user: "bangkok-bowl-user",
  state: "bangkok-bowl-state",
  "chat-session": "bangkok-bowl-chat-session",
  "guest-prefs": "bangkok-bowl-guest-prefs",
};

/**
 * The host this storefront was opened on, lowercased and without its port.
 *
 * The port is dropped so `localhost:5173` and `localhost:4173` — the dev
 * server and a preview build of the same tenant — share a cart rather than
 * quietly having two. `"server"` during SSR, where there is no storage to key
 * and every accessor below returns early anyway.
 */
function host(): string {
  if (typeof window === "undefined") return "server";
  // Optional all the way down: this runs in a few places that stand `window`
  // up by hand — unit tests with a storage stub, and any embedding that does
  // not provide a full `location`. A storefront must not fail to render
  // because it could not work out its own hostname.
  return window.location?.hostname?.toLowerCase() || "unknown";
}

/** `storefront:bhagwati-bakery.localhost:state` */
export function tenantKey(name: StorageName): string {
  return `storefront:${host()}:${name}`;
}

/**
 * Read a key, adopting the pre-tenant value the first time if there is one.
 *
 * Wrapped in try/catch for the same reason the splash screen's pre-paint
 * script is: `localStorage` throws outright in some privacy modes, and a
 * storefront that fails to render because it could not read a cart would be a
 * far worse bug than an empty cart.
 */
export function readTenant(name: StorageName): string | null {
  if (typeof window === "undefined") return null;
  try {
    const key = tenantKey(name);
    const current = window.localStorage.getItem(key);
    if (current !== null) return current;

    const legacy = window.localStorage.getItem(LEGACY[name]);
    if (legacy === null) return null;
    // Adopted rather than copied: leaving the old key behind would mean a
    // second tenant on the same origin inheriting it too, which is the thing
    // being fixed.
    window.localStorage.setItem(key, legacy);
    window.localStorage.removeItem(LEGACY[name]);
    return legacy;
  } catch {
    return null;
  }
}

export function writeTenant(name: StorageName, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(tenantKey(name), value);
  } catch {
    // Full, or blocked. The page keeps working; it just forgets.
  }
}

export function removeTenant(name: StorageName): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(tenantKey(name));
    // The legacy key too, or signing out would leave a stale token behind for
    // the adoption above to pick back up on the next load.
    window.localStorage.removeItem(LEGACY[name]);
  } catch {
    // Nothing to do; see above.
  }
}
