import { createServerFn } from "@tanstack/react-start";
import { getRequestHost } from "@tanstack/react-start/server";

import { API_BASE_URL } from "@/lib/api";
import { FALLBACK_CURRENCY, type CurrencyFormat } from "@/lib/bangkok-data";
import {
  storefrontConfigFrom,
  UNKNOWN_STOREFRONT,
  type AppConfigPayload,
  type StorefrontConfig,
} from "@/lib/storefront";

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
/**
 * Resolved copy, per host, briefly.
 *
 * Every route resolves this for its own `<title>`, because a child route's
 * `head` runs while the root's loader is still pending — `matches` carries the
 * root match with `status: "pending"` and no data, so reading the parent's
 * result is not an option. Each route asking for itself is correct and would
 * otherwise mean two `/app-config` calls to render one page, plus one for
 * every visitor of every storefront.
 *
 * Safe to share across requests: this is a tenant's public branding keyed by
 * the address that selects it, with nothing user-specific in it. Thirty
 * seconds so an owner editing their page title sees it on the next reload
 * rather than wondering whether the save worked.
 */
/** The nameless fallback, with a currency attached so a formatter always has one. */
const UNKNOWN_CONFIG: StorefrontConfig = {
  ...UNKNOWN_STOREFRONT,
  currency: FALLBACK_CURRENCY,
  cover_image_url: null,
};

const TTL_MS = 30_000;
const cache = new Map<string, { at: number; copy: StorefrontConfig }>();

export const getStorefrontCopy = createServerFn({ method: "GET" }).handler(
  async (): Promise<StorefrontConfig> => {
    const host = getRequestHost();
    if (!host) return UNKNOWN_CONFIG;

    const hit = cache.get(host);
    if (hit && Date.now() - hit.at < TTL_MS) return hit.copy;

    try {
      const response = await fetch(
        `${API_BASE_URL}/app-config?host=${encodeURIComponent(host)}`,
        { headers: { Accept: "application/json", "X-Forwarded-Host": host } },
      );
      if (!response.ok) return UNKNOWN_CONFIG;

      const copy = storefrontConfigFrom((await response.json()) as AppConfigPayload);
      // Only a real answer is cached. Caching the fallback would pin a
      // nameless page in place for half a minute after a blip.
      cache.set(host, { at: Date.now(), copy });
      return copy;
    } catch {
      // An unreachable backend must not fail the render. The page still
      // works; only the meta degrades.
      return UNKNOWN_CONFIG;
    }
  },
);
