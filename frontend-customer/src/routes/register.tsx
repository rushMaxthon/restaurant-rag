import { useState } from "react";
import { Link, createFileRoute, useNavigate } from "@tanstack/react-router";
import { AlertCircle, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import heroImage from "@/assets/green-curry.jpg";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";

type RegisterSearch = { redirect: string | undefined };

export const Route = createFileRoute("/register")({
  validateSearch: (search: Record<string, unknown>): RegisterSearch => ({
    redirect: typeof search["redirect"] === "string" ? (search["redirect"] as string) : undefined,
  }),
  head: () => ({
    meta: [
      { title: "Create account — Bangkok Bowl" },
      { name: "description", content: "Create a Bangkok Bowl account to start ordering." },
      { property: "og:title", content: "Create account — Bangkok Bowl" },
      { property: "og:type", content: "website" },
    ],
  }),
  component: RegisterPage,
});

function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const { redirect } = Route.useSearch();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register({ full_name: fullName, email, password, phone_number: phone || null });
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
        <img src={heroImage} alt="Bangkok Bowl green curry" className="absolute inset-0 size-full object-cover" />
        <div className="hero-overlay absolute inset-0" />
        <div className="page-pad relative flex h-full min-h-[calc(100svh-4rem)] max-w-xl flex-col justify-end pb-16 pt-28 text-primary-foreground">
          <Sparkles className="mb-4 size-10" />
          <p className="font-bold">BANGKOK BOWL</p>
          <h1 className="mt-2 font-display text-5xl font-black leading-[.98] sm:text-6xl">Join Bangkok Bowl</h1>
          <p className="mt-5 max-w-md text-lg font-medium">Create an account to order Thai favourites across three Ahmedabad branches.</p>
        </div>
      </div>
      <div className="page-pad flex min-h-[calc(100svh-4rem)] flex-col justify-center py-16">
        <div className="mx-auto w-full max-w-md">
          <h1 className="font-display text-5xl font-black sm:text-6xl">Create your account</h1>
          <p className="mt-3 text-lg text-muted">Order Thai favourites from Bangkok Bowl in minutes.</p>
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
                  <Label htmlFor="full_name">Full name</Label>
                  <Input id="full_name" required minLength={2} value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Your name" className="h-12" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className="h-12" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="phone">Phone number</Label>
                  <Input id="phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Optional" className="h-12" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="password">Password</Label>
                  <Input id="password" type="password" required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 8 characters" className="h-12" />
                </div>
                <Button className="h-12 w-full text-base" type="submit" disabled={submitting}>
                  {submitting ? "Creating account…" : "Create account"}
                </Button>
              </form>
            </CardContent>
          </Card>
          <p className="mt-6 text-center text-muted">
            Already have an account?{" "}
            <Link to="/login" search={{ redirect }} className="font-bold text-primary">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
