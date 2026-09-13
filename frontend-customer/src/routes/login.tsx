import { useState } from "react";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { AlertCircle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import heroImage from "@/assets/pad-thai.jpg";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";

type LoginSearch = { redirect: string | undefined };

export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>): LoginSearch => ({
    redirect: typeof search["redirect"] === "string" ? (search["redirect"] as string) : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Sign in — Bangkok Bowl" },
      { name: "description", content: "Sign in to your Bangkok Bowl account." },
      { property: "og:title", content: "Sign in — Bangkok Bowl" },
      { property: "og:type", content: "website" },
    ],
  }),
  component: LoginPage,
});

function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const { redirect } = Route.useSearch();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      navigate({ to: redirect || "/" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid lg:grid-cols-2">
      <div className="relative hidden lg:block lg:min-h-[calc(100svh-4rem)]">
        <img src={heroImage} alt="Fresh Pad Thai from Bangkok Bowl" className="absolute inset-0 size-full object-cover" />
        <div className="hero-overlay absolute inset-0" />
        <div className="page-pad relative flex h-full min-h-[calc(100svh-4rem)] max-w-xl flex-col justify-end pb-16 pt-28 text-primary-foreground">
          <Sparkles className="mb-4 size-10" />
          <p className="font-bold">BANGKOK BOWL</p>
          <h1 className="mt-2 font-display text-5xl font-black leading-[.98] sm:text-6xl">Sign in for the full menu</h1>
          <p className="mt-5 max-w-md text-lg font-medium">Save favourites, track live orders and reorder your go-to bowl in a tap.</p>
        </div>
      </div>
      <div className="page-pad flex min-h-[calc(100svh-4rem)] flex-col justify-center py-16">
        <div className="mx-auto w-full max-w-md">
          <h1 className="font-display text-5xl font-black sm:text-6xl">Welcome back</h1>
          <p className="mt-3 text-lg text-muted">Sign in to order from Bangkok Bowl.</p>
          <Card className="mt-8 border-border">
            <CardContent className="pt-6">
              <form className="space-y-4" onSubmit={handleSubmit}>
                {error && (
                  <div className="flex items-start gap-2 rounded-md border border-danger bg-danger/10 p-3 text-sm font-semibold text-danger">
                    <AlertCircle className="mt-0.5 size-4 shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className="h-12" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="password">Password</Label>
                  <Input id="password" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" className="h-12" />
                </div>
                <Button className="h-12 w-full text-base" type="submit" disabled={submitting}>
                  {submitting ? "Signing in…" : "Sign in"}
                </Button>
              </form>
            </CardContent>
          </Card>
          <p className="mt-6 text-center text-muted">
            New here?{" "}
            <Link to="/register" search={{ redirect }} className="font-bold text-primary">
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
