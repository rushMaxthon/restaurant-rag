# frontend-customer

The customer-facing storefront: one deployment that serves every restaurant on
the platform, resolved from the address the request arrives on.

`radhe-dhokla.localhost:5173` and `bangkok-bowl.localhost:5173` are the same
build. The root route asks `/app-config` who the host belongs to, and that one
answer carries the restaurant's name, branding, currency, storefront copy and
which optional features it has — so the first server-rendered byte is already
the right restaurant's, rather than the wrong one being corrected after a
fetch.

## Running it

```bash
npm run dev -- --port 5173 --strictPort   # the API expects this port in CORS
npm run build                             # nitro output in .output/
npm run test                              # vitest, node environment
./node_modules/.bin/tsc --noEmit
```

The API must be running at `http://localhost:8000`; see `backend/README` and
the root `CLAUDE.md`. Tenants resolve through `*.localhost`, which browsers
send to 127.0.0.1 without any hosts-file entry.

## Stack

TanStack Start (file-based routing, SSR via nitro), React 19, Tailwind v4
configured entirely in `src/styles.css`, TanStack Query, and a small number of
shadcn primitives that are mostly unused — the look lives in `src/styles.css`
and `src/polish.css` rather than in a component library.

`vite.config.ts` composes the build explicitly and says why each piece is
there. It is worth reading before changing: the plugin order matters, and the
`importProtection` override is what lets `lib/storefront.server.ts` be
imported from a route.

## The rules that are easy to break

**Nothing is claimed until it is known.** This app serves one restaurant's
customers at a time and every sentence on screen is about a real business. A
section headed "Crowd favourites" over dishes nobody has favourited, a "Top
rated" sort on a menu with no ratings, a price in the wrong currency, or one
restaurant's monogram on another's site are all the same bug, and all of them
have shipped here before. Where the data cannot support the claim, the copy
changes.

**Money is never a literal.** Prices come from the restaurant's own currency
via `useMoney`; a budget in prose uses `useRoundedMoney`. There is no `$` in
this codebase that is not a bug.

**Server state belongs to the server.** Availability, payment methods, slot
validity and totals are all re-checked by the API. Hiding a control here is a
convenience, never the rule.
