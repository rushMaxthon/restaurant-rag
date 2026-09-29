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

type RegisterSearch = { redirect: string | undefined };

export const Route = createFileRoute("/register")({
  validateSearch: (search: Record<string, unknown>): RegisterSearch => ({
    redirect: typeof search["redirect"] === "string" ? (search["redirect"] as string) : undefined,
  }),
  loader: () => getStorefrontCopy(),
  head: ({ loaderData }) => ({
    meta: pageMeta(loaderData, "Create account", "Create an account to start ordering."),
  }),
  component: RegisterPage,
});

function RegisterPage() {
  // This restaurant's own words, resolved by the root route from the
  // address the page was opened on.
  const copy = useStorefrontCopy();
  const { register, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const { redirect } = Route.useSearch();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
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
      await register({ full_name: fullName, email, password, phone_number: phone || null });
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
            Join {copy.name}
          </h1>
          <p className="mt-5 max-w-md text-lg font-medium">
            Create an account to order from {copy.name}.
          </p>
        </div>
      </StorefrontHero>
      <div className="page-pad flex min-h-[calc(100svh-4rem)] flex-col justify-center py-16">
        <div className="mx-auto w-full max-w-md">
          <h1 className="auth-heading font-display text-5xl font-extrabold sm:text-6xl">
            Create your account
          </h1>
          <p className="auth-sub mt-3 text-lg text-muted">Order from {copy.name} in minutes.</p>
          <Card className="auth-card elevated-panel mt-8">
            <CardContent className="pt-6">
              <form className="space-y-4" onSubmit={handleSubmit}>
                {error && (
                  <div className="inline-error form-error" role="alert">
                    <AlertCircle className="mt-0.5 size-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label htmlFor="full_name">Full name</Label>
                  <Input
                    id="full_name"
                    required
                    minLength={2}
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Your name"
                    className="h-12"
                  />
                </div>
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
                  <Label htmlFor="phone">Phone number</Label>
                  <Input
                    id="phone"
                    type="tel"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="Optional"
                    className="h-12"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="password">Password</Label>
                  <PasswordInput
                    id="password"
                    autoComplete="new-password"
                    minLength={8}
                    value={password}
                    onChange={setPassword}
                    placeholder="At least 8 characters"
                  />
                </div>
                <Button className="h-12 w-full text-base" type="submit" disabled={submitting}>
                  {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
                  {submitting ? "Creating account…" : "Create account"}
                </Button>
              </form>
            </CardContent>
          </Card>
          <p className="auth-foot mt-6 text-center text-muted">
            Already have an account?{" "}
            <Link
              to="/login"
              search={{ redirect: sanitizeRedirect(redirect) }}
              className="auth-link"
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
