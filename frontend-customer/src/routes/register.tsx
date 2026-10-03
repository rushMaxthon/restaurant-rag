import { createFileRoute, redirect } from "@tanstack/react-router";

import { sanitizeRedirect } from "@/lib/require-auth";

type RegisterSearch = { redirect: string | undefined };

/**
 * There is no separate sign-up any more.
 *
 * A number is the whole identity: the first code it receives creates the
 * account, so there is nothing to register, no password to invent and none to
 * reset. This route stays as a redirect rather than being deleted, because
 * links to it exist — in somebody's bookmarks, in an old email, in a message
 * sent before the change — and a 404 is a worse answer than the form that
 * replaced it.
 *
 * The redirect is thrown from `beforeLoad`, so it happens before anything
 * renders and carries the `redirect` parameter through: somebody who was sent
 * here on their way to the checkout still lands back at the checkout.
 */
export const Route = createFileRoute("/register")({
  validateSearch: (search: Record<string, unknown>): RegisterSearch => ({
    redirect: typeof search["redirect"] === "string" ? (search["redirect"] as string) : undefined,
  }),
  beforeLoad: ({ search }) => {
    throw redirect({
      to: "/login",
      // Sanitised rather than passed through: this value reaches a navigation,
      // and `sanitizeRedirect` is what stops an open redirect — the same
      // treatment the sign-in form gives it.
      search: { redirect: sanitizeRedirect(search.redirect) },
      replace: true,
    });
  },
});
