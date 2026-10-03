import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { useEffect, type ReactNode } from "react";

import appCss from "../styles.css?url";
import polishCss from "../polish.css?url";
import { reportError } from "../lib/error-reporting";
import { BangkokStoreProvider } from "@/lib/bangkok-store";
import { RealtimeProvider } from "@/lib/realtime-provider";
import { AuthProvider } from "@/lib/auth";
import { AppShell } from "@/components/bangkok/app-shell";
import { UNKNOWN_STOREFRONT, storefrontMeta } from "@/lib/storefront";
import { fontTokenCss, resolveFonts } from "@/lib/fonts";
import { faviconHref } from "@/lib/favicon";
import { RELOAD_TO_TOP_PREPAINT } from "@/lib/reload-to-top";
import { getStorefrontCopy } from "@/lib/storefront.server";
import { Button } from "@/components/ui/button";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  useEffect(() => {
    reportError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          This page didn't load
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Something went wrong on our end. You can try refreshing or head back home.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <Button
            onClick={() => {
              router.invalidate();
              reset();
            }}
          >
            Try again
          </Button>
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  // Resolved from the address the request arrived on, so every page of every
  // tenant is titled for that tenant. These nine strings used to be Bangkok
  // Bowl's literals, which meant six restaurants shared one restaurant's
  // name in every browser tab, link preview and search result.
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => {
    // Resolved HERE rather than after hydration because a typeface is the one
    // branding decision that has to be settled before the first paint. Fetched
    // on the client, every visitor would watch the page re-set itself in a
    // different family a beat after it appeared.
    const fonts = resolveFonts(loaderData?.font_family);
    return {
      meta: [
        { charSet: "utf-8" },
        { name: "viewport", content: "width=device-width, initial-scale=1" },
        ...storefrontMeta(loaderData ?? UNKNOWN_STOREFRONT),
      ],
      links: [
        // The chosen face first, and preconnected, because it is the only
        // render-blocking asset here that the reader actually sees arrive.
        ...fonts.hrefs.map((href) => ({ rel: "stylesheet", href })),
        { rel: "stylesheet", href: appCss },
        { rel: "stylesheet", href: polishCss },
        // This restaurant's own icon, not the platform's and certainly not
        // the generator's. `/favicon.ico` was hardcoded, so every tenant wore
        // Lovable's mark in the tab, in a bookmark and on a home screen — the
        // same class of mistake as the shared hero photograph, in the places
        // a brand is most visible and least often checked.
        { rel: "icon", href: faviconHref(loaderData ?? UNKNOWN_STOREFRONT) },
      ],
      // After the stylesheets, so it wins over the token file's defaults
      // without needing !important or a higher specificity.
      styles: [{ children: fontTokenCss(fonts) }],
    };
  },
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  const storefront = Route.useLoaderData() as typeof UNKNOWN_STOREFRONT | undefined;
  return (
    <html lang="en">
      <head>
        {/* Before anything renders, because it has to reach the router's
            cached scroll position before the router does. See
            `reload-to-top.ts`. */}
        <script dangerouslySetInnerHTML={{ __html: RELOAD_TO_TOP_PREPAINT }} />
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        {/* Inside AuthProvider for the token, and around everything else so
            any screen can read whether pushes are arriving. */}
        <RealtimeProvider>
          <BangkokStoreProvider>
            <AppShell>
              <Outlet />
            </AppShell>
          </BangkokStoreProvider>
        </RealtimeProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
