import { useEffect, useState } from "react";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { AlertCircle, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { StorefrontHero } from "@/components/bangkok/storefront-hero";
import { useAuth } from "@/lib/auth";
import { PasswordInput } from "@/components/bangkok/password-input";
import { sanitizeRedirect } from "@/lib/require-auth";
import { ApiError } from "@/lib/api";
import { pageMeta, useStorefrontCopy } from "@/lib/storefront";
import { getStorefrontCopy } from "@/lib/storefront.server";

type LoginSearch = { redirect: string | undefined; expired?: boolean | undefined };

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    redirect: typeof search["redirect"] === "string" ? (search["redirect"] as string) : undefined,
    // Set when the app sent them here because the token it held stopped being
    // accepted. Arriving at a sign-in page you did not ask for, with no
    // explanation, is its own small bewilderment.
    expired: search["expired"] === true || search["expired"] === "true" ? true : undefined,
  }),
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Sign in", "Sign in to your account to order."),
  }),
  component: LoginPage,
});

function LoginPage() {
  // This restaurant's own words, resolved by the root route from the
  // address the page was opened on.
  const copy = useStorefrontCopy();
  const { login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const { redirect, expired } = Route.useSearch();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Someone who is already signed in has no business on this form — bounce
  // them to where they were headed. `replace` keeps it out of history, so Back
  // does not land them right back here.
  const target = sanitizeRedirect(redirect) ?? "/";
  useEffect(() => {
    if (isAuthenticated) navigate({ to: target, replace: true });
  }, [isAuthenticated, navigate, target]);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate({ to: target });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid lg:grid-cols-2">
      <StorefrontHero className="hidden lg:block lg:min-h-[calc(100svh-4rem)]">
        <div className="hero-overlay absolute inset-0" />
        <div className="hero-copy page-pad relative flex h-full min-h-[calc(100svh-4rem)] max-w-xl flex-col justify-end pb-16 pt-28 text-primary-foreground">
          <Sparkles className="mb-4 size-10" />
          <p className="eyebrow eyebrow--inherit">{copy.name}</p>
          <h1 className="font-display text-5xl font-extrabold leading-[.98] sm:text-6xl">
            Sign in for the full menu
          </h1>
          <p className="mt-5 max-w-md text-lg font-medium">
            Save favourites, track live orders and reorder what you always get, in a tap.
          </p>
        </div>
      </StorefrontHero>
      <div className="page-pad flex min-h-[calc(100svh-4rem)] flex-col justify-center py-16">
        <div className="mx-auto w-full max-w-md">
          <h1 className="auth-heading font-display text-5xl font-extrabold sm:text-6xl">
            Welcome back
          </h1>
          <p className="auth-sub mt-3 text-lg text-muted">{copy.login_blurb}</p>
          <Card className="auth-card elevated-panel mt-8">
            <CardContent className="pt-6">
              <form className="space-y-4" onSubmit={handleSubmit}>
                {expired && !error && (
                  <div className="inline-error form-error" role="status">
                    <AlertCircle className="mt-0.5 size-4 shrink-0" />
                    <span>
                      Your sign-in expired, so we brought you here. Everything you had is
                      saved — sign in and you will go straight back.
                    </span>
                  </div>
                )}
                {error && (
                  <div className="inline-error form-error" role="alert">
                    <AlertCircle className="mt-0.5 size-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    required
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="h-12"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="password">Password</Label>
                  <PasswordInput
                    id="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={setPassword}
                  />
                </div>
                <Button className="h-12 w-full text-base" type="submit" disabled={submitting}>
                  {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
                  {submitting ? "Signing in…" : "Sign in"}
                </Button>
              </form>
            </CardContent>
          </Card>
          <p className="auth-foot mt-6 text-center text-muted">
            New here?{" "}
            <Link
              to="/register"
              search={{ redirect: sanitizeRedirect(redirect) }}
              className="auth-link"
            >
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
