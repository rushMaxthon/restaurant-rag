import { useLoaderData } from "@tanstack/react-router";

/**
 * This restaurant's own words.
 *
 * Page title, meta description and hero copy used to be string literals in
 * `routes/index.tsx` and `routes/__root.tsx`, so all six tenants shared one
 * restaurant's name — in every browser tab, every link preview and every
 * search result. The strings now come from the restaurant's own record,
 * resolved from the address the request arrived on.
 *
 * The server half lives in `storefront.server.ts`, because reading the
 * incoming request is something only the server can do.
 */
export type StorefrontCopy = {
  /**
   * The restaurant's name, for page titles like "Your cart — Radhe Dhokla".
   *
   * Separate from `hero_headline`, which starts as the name but is the one
   * field an owner is most likely to rewrite into a slogan — and "Your cart —
   * Wok this way" is not a page title.
   */
  name: string;
  meta_title: string;
  meta_description: string;
  og_title: string;
  og_description: string;
  hero_headline: string;
  hero_subcopy: string;
  concierge_intro: string;
  login_blurb: string;
};

/**
 * What the page says when the backend cannot be reached.
 *
 * Deliberately nameless. A storefront that cannot reach its API has no way to
 * know which restaurant it is, and naming one — the old behaviour, and the
 * reason this file exists — puts a real restaurant's name on a page that is
 * not theirs. "Order online" tells a crawler nothing, and telling it nothing
 * beats telling it something false.
 */
export const UNKNOWN_STOREFRONT: StorefrontCopy = {
  name: "this kitchen",
  meta_title: "Order online",
  meta_description: "Browse the menu and order online.",
  og_title: "Order online",
  og_description: "Browse the menu and order online.",
  hero_headline: "Order online",
  hero_subcopy: "Browse the menu and order online.",
  concierge_intro: "Ask me anything about the menu.",
  login_blurb: "Sign in to place your order.",
};

/** The meta tags a storefront's copy produces, shared by every route. */
export function storefrontMeta(copy: StorefrontCopy) {
  return [
    { title: copy.meta_title },
    { name: "description", content: copy.meta_description },
    { name: "author", content: copy.hero_headline },
    { property: "og:title", content: copy.og_title },
    { property: "og:description", content: copy.og_description },
    { property: "og:type", content: "website" },
    { name: "twitter:card", content: "summary_large_image" },
  ];
}

/**
 * The copy the root route resolved, from anywhere in the tree.
 *
 * A read rather than a fetch: these strings were in the HTML before it was
 * sent, so a page that shows them should not pay for them again. Read off the
 * root route by id rather than imported from it, which would be a cycle —
 * `__root.tsx` imports this module.
 */
export function useStorefrontCopy(): StorefrontCopy {
  const data = useLoaderData({ from: "__root__" }) as StorefrontCopy | undefined;
  return data ?? UNKNOWN_STOREFRONT;
}

/**
 * A page title for a route inside the storefront: "Your cart — Radhe Dhokla".
 *
 * Takes the copy from the route's OWN loader rather than reaching up to the
 * root's. A child route's `head` runs while the root loader is still pending —
 * `matches` carries the root with `status: "pending"` and no data — so the
 * parent's result genuinely is not available yet, and reading it produced
 * "Your cart — this kitchen" on every page. The server fn each route calls is
 * cached per host, so asking again costs nothing.
 *
 * Eleven routes used to spell "Bangkok Bowl" into their own titles, so eleven
 * pages of every tenant's website were named after one restaurant.
 */
export function pageMeta(
  copy: StorefrontCopy | undefined,
  page: string,
  description: string,
) {
  const title = `${page} — ${(copy ?? UNKNOWN_STOREFRONT).name}`;
  return [
    { title },
    { name: "description", content: description },
    { property: "og:title", content: title },
    { property: "og:description", content: description },
    { property: "og:type", content: "website" },
  ];
}
