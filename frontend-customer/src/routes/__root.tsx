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
import { SPLASH_PREPAINT, SplashScreen } from "@/components/bangkok/splash-screen";
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
        { rel: "icon", href: "/favicon.ico", type: "image/x-icon" },
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
    // `suppressHydrationWarning` because `SPLASH_PREPAINT` runs in the head,
    // before React, and sets `data-splash="seen"` on this element for a repeat
    // visit. The server cannot know what is in the visitor's sessionStorage,
    // so the attribute is on the client and not in the SSR HTML, and React
    // reports the difference as a hydration mismatch on every second page
    // view. This is the documented escape for exactly that: a pre-paint script
    // writing to <html>, the same pattern a theme script uses. It suppresses
    // the warning for THIS element's attributes only — children are still
    // checked — and nothing else about the element is written by the server.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Before anything renders, so a second page in the same visit never
            flashes the splash. React cannot run early enough to prevent that,
            which is the same reason the operator panel inlines its theme
            script. */}
        <script dangerouslySetInnerHTML={{ __html: SPLASH_PREPAINT }} />
        {/* Also before anything renders, and for the same reason: it has to
            get to the router's cached scroll position before the router
            does. See `reload-to-top.ts`. */}
        <script dangerouslySetInnerHTML={{ __html: RELOAD_TO_TOP_PREPAINT }} />
        <HeadContent />
      </head>
      <body>
        {/* Over the page, not instead of it: the menu, the copy and the meta
            tags are all in this same response whether the overlay renders or
            not, so a crawler reads the storefront either way. */}
        <SplashScreen name={(storefront ?? UNKNOWN_STOREFRONT).name} />
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
