import { useEffect, useRef, useState } from "react";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { AlertCircle, ArrowLeft, Loader2, Smartphone, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { StorefrontHero } from "@/components/bangkok/storefront-hero";
import { useAuth } from "@/lib/auth";
import { sanitizeRedirect } from "@/lib/require-auth";
import { api, ApiError } from "@/lib/api";
import { useBangkokStore } from "@/lib/bangkok-store";
import { formatPhoneAsTyped } from "@/lib/delivery-address";
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

/**
 * Signing in.
 *
 * A phone number and a code, which is what a customer ordering food in India
 * expects and what every app they already use does — no password to invent on
 * a phone keyboard and none to forget six weeks later. The account is created
 * on the way through: there is no separate sign-up, because "do you have an
 * account" is a question the number already answers.
 *
 * **There is no email and password here any more, and no separate sign-up.**
 * A number is the whole identity: the account is created on the way through,
 * so there is nothing to register and nothing to reset.
 *
 * An email form did sit behind a link for a while, and it had to go for a
 * reason worth remembering. The phone form asked the server whether it could
 * send a code and quietly switched to email when the answer was no — so a
 * backend that was restarting, for one request, left somebody looking at a
 * password box they had never seen and could not use. A form that changes
 * what it is asking for because of a transient server state is worse than one
 * that says it cannot do the thing right now.
 *
 * Staff do not sign in here at all; the operator panel has its own form
 * against the same backend route, which is untouched.
 */
function LoginPage() {
  // This restaurant's own words, resolved by the root route from the
  // address the page was opened on.
  const copy = useStorefrontCopy();
  const store = useBangkokStore();
  const { signInWithOtp, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const { redirect, expired } = Route.useSearch();

  const [step, setStep] = useState<"number" | "code">("number");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [fullName, setFullName] = useState("");
  const [isNewAccount, setIsNewAccount] = useState(false);
  const [debugCode, setDebugCode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const codeRef = useRef<HTMLInputElement>(null);

  // Someone who is already signed in has no business on this form — bounce
  // them to where they were headed. `replace` keeps it out of history, so Back
  // does not land them right back here.
  const target = sanitizeRedirect(redirect) ?? "/";
  useEffect(() => {
    if (isAuthenticated) navigate({ to: target, replace: true });
  }, [isAuthenticated, navigate, target]);

  // Straight into the code box once it appears: the customer has just been
  // told to type a code and should not have to find where.
  useEffect(() => {
    if (step === "code") codeRef.current?.focus();
  }, [step]);

  function explain(err: unknown): string {
    if (err instanceof ApiError) return err.message;
    return "Something went wrong. Please try again.";
  }

  async function sendCode(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const reply = await api.requestOtp(phone);
      setIsNewAccount(reply.is_new_account);
      setDebugCode(reply.debug_code);
      setStep("code");
    } catch (err) {
      setError(explain(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function verifyCode(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await signInWithOtp({
        phone_number: phone,
        code,
        // Only meaningful for a number with no account yet; the server ignores
        // it otherwise, so a returning customer's name cannot be rewritten by
        // a sign-in form.
        full_name: isNewAccount ? fullName.trim() || null : null,
      });
      navigate({ to: target });
    } catch (err) {
      setError(explain(err));
    } finally {
      setSubmitting(false);
    }
  }

  const notices = (
    <>
      {expired && !error && (
        <div className="inline-error form-error" role="status">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>
            Your sign-in expired, so we brought you here. Everything you had is saved — sign in and
            you will go straight back.
          </span>
        </div>
      )}
      {error && (
        <div className="inline-error form-error" role="alert">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}
    </>
  );

  return (
    <div className="grid lg:grid-cols-2">
      <StorefrontHero className="hidden lg:block lg:min-h-[calc(100svh-4rem)]">
        <div className="hero-overlay absolute inset-0" />
        <div className="hero-copy page-pad relative flex h-full min-h-[calc(100svh-4rem)] max-w-xl flex-col justify-end pb-16 pt-28">
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
            {step === "code" && isNewAccount ? "Almost there" : "Welcome back"}
          </h1>
          <p className="auth-sub mt-3 text-lg text-muted">
            {step === "code"
              ? `We sent a code to ${store.phoneCountryCode ?? ""} ${phone}`.trim()
              : copy.login_blurb}
          </p>

          <Card className="auth-card elevated-panel mt-8">
            <CardContent className="pt-6">
              {step === "number" && (
                <form className="space-y-4" onSubmit={sendCode}>
                  {notices}
                  <div className="space-y-1.5">
                    <Label htmlFor="phone">Phone number</Label>
                    <div className="field-wrap">
                      {/* From the server, like the checkout's: a literal here
                          could disagree with the code the number is stored
                          under, with nothing to say so. */}
                      {store.phoneCountryCode && (
                        <span className="country-code">{store.phoneCountryCode}</span>
                      )}
                      <Input
                        id="phone"
                        required
                        type="tel"
                        inputMode="tel"
                        autoComplete="tel-national"
                        autoFocus
                        placeholder="(555) 000-0000"
                        value={phone}
                        onChange={(e) => setPhone(formatPhoneAsTyped(e.target.value))}
                        className="h-12"
                      />
                    </div>
                  </div>
                  <Button className="h-12 w-full text-base" type="submit" disabled={submitting}>
                    {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
                    {submitting ? "Sending…" : "Send code"}
                  </Button>
                  <p className="text-center text-sm text-muted">
                    No password needed. We will text you a code.
                  </p>
                </form>
              )}

              {step === "code" && (
                <form className="space-y-4" onSubmit={verifyCode}>
                  {notices}
                  {debugCode && (
                    // Not `inline-error`: this is information, and a red
                    // panel above a form somebody has not submitted yet reads
                    // as something already being wrong.
                    <div className="closed-notice" data-tone="soft" role="status">
                      <Smartphone className="mt-0.5 size-4 shrink-0 text-primary" />
                      <span className="text-sm">
                        No SMS is set up here yet, so your code is <strong>{debugCode}</strong>.
                      </span>
                    </div>
                  )}
                  {isNewAccount && (
                    <div className="space-y-1.5">
                      <Label htmlFor="full_name">Your name</Label>
                      <Input
                        id="full_name"
                        autoComplete="name"
                        placeholder="So we know what to call you"
                        value={fullName}
                        onChange={(e) => setFullName(e.target.value)}
                        className="h-12"
                      />
                    </div>
                  )}
                  <div className="space-y-1.5">
                    <Label htmlFor="code">Your code</Label>
                    <Input
                      id="code"
                      ref={codeRef}
                      required
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={8}
                      placeholder="123456"
                      value={code}
                      onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                      className="otp-input h-12"
                    />
                  </div>
                  <Button className="h-12 w-full text-base" type="submit" disabled={submitting}>
                    {submitting && <Loader2 className="animate-spin" aria-hidden="true" />}
                    {submitting ? "Checking…" : isNewAccount ? "Create my account" : "Sign in"}
                  </Button>
                  <button
                    type="button"
                    className="auth-link mx-auto flex items-center gap-1.5 text-sm"
                    onClick={() => {
                      setStep("number");
                      setCode("");
                      setError(null);
                    }}
                  >
                    <ArrowLeft className="size-4" aria-hidden="true" />
                    Use a different number
                  </button>
                </form>
              )}
            </CardContent>
          </Card>

          {/* No "create an account" link: there is no account to create
              separately. The first code a number receives makes one. */}
          <p className="auth-foot mt-6 text-center text-muted">
            Your number is your account — we will make one if you are new.
          </p>
        </div>
      </div>
    </div>
  );
}
