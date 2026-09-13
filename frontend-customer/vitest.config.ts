import { defineConfig } from "vitest/config";
import path from "node:path";

// Standalone rather than a `test` block inside vite.config.ts: that file wraps
// @lovable.dev/vite-tanstack-config, which injects the TanStack Start, nitro
// and router plugins. None of them are wanted for a plain logic test run, and
// the router plugin fails outside a dev/build context.
export default defineConfig({
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
