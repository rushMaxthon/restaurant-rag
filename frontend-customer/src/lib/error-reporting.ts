/**
 * What to do with an error the root boundary caught.
 *
 * This was `lovable-error-reporting.ts`, which handed the error to
 * `window.__lovableEvents` and `window.__lovableReportRuntimeError` — globals
 * the generator's editor preview injects. Neither exists anywhere this app is
 * actually served, so every boundary-caught error went nowhere at all.
 *
 * The one genuinely useful thing it did is kept: naming the error. Loaders and
 * server functions throw a raw `Response` as a control-flow device, and
 * `String(response)` is the opaque "[object Response]" — so a redirect or a
 * 404 arriving here used to be indistinguishable from any other failure.
 */

export function describeError(error: unknown): string {
  if (error instanceof Response) {
    return `Response ${error.status}${error.url ? ` at ${error.url}` : ""}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

export function reportError(error: unknown, context: Record<string, unknown> = {}) {
  if (typeof window === "undefined") {
    return;
  }
  // The console, deliberately, and nothing else. Wiring this to a real error
  // service is a decision with a cost attached — an account, a DSN in the
  // bundle, and customer data leaving the country — so it is left to whoever
  // takes that decision rather than assumed here.
  console.error("[storefront]", describeError(error), {
    route: window.location.pathname,
    ...context,
  });
}
