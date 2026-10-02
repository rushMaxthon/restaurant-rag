import { QueryClient } from "@tanstack/react-query";
import { createRouter } from "@tanstack/react-router";
import { routeTree } from "./routeTree.gen";

export const getRouter = () => {
  const queryClient = new QueryClient();

  const router = createRouter({
    routeTree,
    context: { queryClient },
    scrollRestoration: true,
    /**
     * The scroll key is deliberately left at TanStack's default.
     *
     * It was overridden with `(location) => location.href` on the belief that
     * the default keys by pathname, so `/menu` and `/menu?category=Sweets`
     * would share one saved position. That belief was wrong. The default is
     * `location.state.__TSR_key || location.href` — a key per HISTORY ENTRY,
     * which already tells those two apart.
     *
     * Keying by address instead broke every ordinary navigation, because an
     * address is not a visit. Clicking "Menu" from a home page scrolled
     * halfway down restored wherever `/menu` had last been left — on a first
     * visit, the position inherited from the page before it — and clicking
     * the logo to go home dropped the reader 2,000px into it. A link should
     * land at the top; only back and forward should return you to where you
     * were, and the per-entry key is what distinguishes those two.
     *
     * The menu rail does not need this override either: it navigates with
     * `resetScroll: false` (see `menu.index.tsx`), which stops the router
     * touching the scroll position at all.
     */
    defaultPreloadStaleTime: 0,
  });

  return router;
};
