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
     * Remember a scroll position per ADDRESS, not per path.
     *
     * The default key is the pathname, so `/menu` and `/menu?category=Sweets`
     * share one saved position. The menu is a single 36,000px page whose
     * section lives in the search params, and it scrolls itself to that
     * section on arrival — so sharing a key means the router restores the
     * position saved for the top of the menu over a jump that has already
     * landed on the right section. It reproduced as a shared link to a section
     * working from a cold tab and doing nothing from a tab that had the menu
     * open a moment earlier.
     *
     * Keying on the full address also makes back and forward do the more
     * useful thing: return to the section you were reading rather than to
     * wherever the menu was last left.
     */
    getScrollRestorationKey: (location) => location.href,
    defaultPreloadStaleTime: 0,
  });

  return router;
};
