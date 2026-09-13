import { useEffect, useRef } from "react";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useAuth } from "@/lib/auth";

/** Screens that must never be a redirect target — see sanitizeRedirect. */
const AUTH_PATHS = new Set(["/login", "/register"]);

/**
 * Reduce a router href to something safe to hand back to /login?redirect=.
 *
 * Two things have to be true. It must be a same-origin path, because the value
 * arrives from the query string and an absolute URL there is an open redirect.
 * And it must not point at an auth screen: sending the visitor back to /login
 * after they log in is how the URL grew to 4,000 characters of nested
 * %2525252F — each bounce re-encoded the previous one.
 */
export function sanitizeRedirect(href: string | undefined): string | undefined {
  if (!href) return undefined;
  // "//evil.com" is protocol-relative and would leave the origin.
  if (!href.startsWith("/") || href.startsWith("//")) return undefined;
  const path = href.split("?")[0]!.split("#")[0]!;
  if (AUTH_PATHS.has(path)) return undefined;
  return href;
}

/**
 * Gate a route on being signed in, sending the visitor to /login and back.
 *
 * The href is read through a ref rather than a dependency on purpose. The
 * guard's own navigate() changes the href, so listing it as a dependency makes
 * the effect re-fire on the URL it just produced and wrap it again — which is
 * exactly the loop that produced the endless ?redirect=%2Flogin%3Fredirect%3D…
 * Reading it at fire time keeps the target correct without re-triggering.
 */
export function useRequireAuth(): boolean {
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const href = useRouterState({ select: (s) => s.location.href });
  const hrefRef = useRef(href);
  hrefRef.current = href;

  useEffect(() => {
    if (isAuthenticated) return;
    navigate({
      to: "/login",
      search: { redirect: sanitizeRedirect(hrefRef.current) },
      // replace, so Back from the login screen returns to where they were
      // rather than re-entering the guard and bouncing again.
      replace: true,
    });
  }, [isAuthenticated, navigate]);

  return isAuthenticated;
}
