import { createServerFn } from "@tanstack/react-start";
import { getRequestHost } from "@tanstack/react-start/server";

import { API_BASE_URL } from "@/lib/api";
import { UNKNOWN_STOREFRONT, type StorefrontCopy } from "@/lib/storefront";

/**
 * Resolve this restaurant's copy from the address the request arrived on.
 *
 * The brand, menu and branches all arrive through `useAppConfig`, which runs
 * in the browser after hydration — fine, because nobody reads a page before
 * it hydrates. The `<title>` and meta description are the exception: a
 * crawler and a link preview both read the FIRST HTML response and never
 * wait. Fetched on the client they would be missing from every result for
 * every tenant, which is the version of this bug that does lasting damage.
 *
 * A server function rather than a plain loader because `getRequestHost` only
 * exists on the server. During SSR this runs in process; on a client-side
 * navigation it becomes one RPC call, which the router caches for the life of
 * the page.
 *
 * Kept in its own module so the server-only import above cannot be pulled
 * into the browser bundle by anything that wants the types or the hook.
 */
export const getStorefrontCopy = createServerFn({ method: "GET" }).handler(
  async (): Promise<StorefrontCopy> => {
    const host = getRequestHost();
    if (!host) return UNKNOWN_STOREFRONT;

    try {
      const response = await fetch(
        `${API_BASE_URL}/app-config?host=${encodeURIComponent(host)}`,
        { headers: { Accept: "application/json", "X-Forwarded-Host": host } },
      );
      if (!response.ok) return UNKNOWN_STOREFRONT;

      const payload = (await response.json()) as {
        storefront?: Partial<StorefrontCopy>;
      };
      // Merged rather than trusted wholesale: the backend fills every key for
      // a restaurant, but a MARKETPLACE client legitimately sends none.
      return { ...UNKNOWN_STOREFRONT, ...(payload.storefront ?? {}) };
    } catch {
      // An unreachable backend must not fail the render. The page still
      // works; only the meta degrades.
      return UNKNOWN_STOREFRONT;
    }
  },
);
