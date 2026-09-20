import { fileURLToPath } from "node:url";
import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import react from "@vitejs/plugin-react";
import { nitro } from "nitro/vite";
import { defineConfig } from "vite";
import tsConfigPaths from "vite-tsconfig-paths";

/**
 * The build, written out.
 *
 * This wrapped `@lovable.dev/vite-tanstack-config`, which composed the plugins
 * below and could not be read without unpacking its dist. Everything it
 * supplied is reproduced here, in its order, from packages this app already
 * depends on directly — so the build is something this repo owns and can be
 * understood by reading one file.
 *
 * The order is the wrapper's and is not arbitrary: tsconfig paths and Tailwind
 * before TanStack Start, Start before React, and nitro last. Its `@` alias and
 * its dedupe list are reproduced exactly; the dedupe is the one piece that
 * looks optional and is not, because two copies of React in one graph is a
 * hook dispatcher error at runtime rather than a build failure.
 *
 * Dropped with it: that package's dev-only TanStack devtools (its own
 * dependency, not this app's) and its sandbox port detection, which existed to
 * serve the app inside the generator's preview.
 */
const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "src");

export default defineConfig(({ command }) => ({
  plugins: [
    tsConfigPaths(),
    tailwindcss(),
    tanstackStart({
      // `src/server.ts` is this app's SSR error wrapper; Start builds from it.
      server: { entry: "server" },
      /**
       * NOT decoration, and not safe to drop.
       *
       * Start's default import protection denies `**\/*.server.*` from the
       * client graph, and this app keeps `lib/storefront.server.ts` — a
       * server function imported by `__root.tsx`, which is exactly the
       * pattern Start extracts rather than bundles. The wrapper replaced the
       * default patterns with these, so the build worked; reproducing the
       * plugin without them fails on that import, which is how this was
       * found.
       */
      importProtection: {
        behavior: "error",
        client: { files: ["**/server/**"], specifiers: ["server-only"] },
      },
    }),
    react(),
    // Build only, as the wrapper had it: the dev server is Vite's own, and
    // nitro is what produces `.output` for deployment.
    ...(command === "build" ? [nitro()] : []),
  ],
  resolve: {
    alias: { "@": src },
    // One copy of each, or a second React sees no hook dispatcher and every
    // component throws on its first `useState`.
    dedupe: [
      "react",
      "react-dom",
      "react/jsx-runtime",
      "react/jsx-dev-runtime",
      "@tanstack/react-query",
      "@tanstack/query-core",
    ],
  },
}));
