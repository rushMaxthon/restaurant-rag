import { Eye, EyeOff, Lock, Mail } from 'lucide-react';
import { useState } from 'react';
import { ApiError, api } from '../services/api';
import { useAdminStore } from '../hooks/useAdminStore';

interface LoginPageProps {
  onSuccess: (path: string) => void;
}

export function LoginPage({ onSuccess }: LoginPageProps) {
  const { setSession, pushToast } = useAdminStore();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const response = await api.login({ email, password });
      if (response.role !== 'ADMIN' && response.role !== 'OWNER') {
        throw new ApiError(
          'Customer accounts cannot access the admin panel.',
          403,
        );
      }
      setSession({
        token: response.access_token,
        role: response.role,
        restaurantId: response.restaurant_id,
        user: response.user,
      });
      pushToast('Signed in', 'Dashboard access granted.', 'success');
      onSuccess(
        response.role === 'OWNER' && response.restaurant_id
          ? `/admin/restaurants/${response.restaurant_id}`
          : '/dashboard',
      );
    } catch (loginError: unknown) {
      const message =
        loginError instanceof ApiError ? loginError.message : 'Unable to sign in.';
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-shell">
      <form className="login-card lg-card" onSubmit={submit}>
        <div className="lg-brand">
          <span className="lg-brand__mark">RR</span>
          <div className="lg-brand__copy">
            <strong>Restaurant RAG</strong>
            <span>Admin &amp; Owner Console</span>
          </div>
        </div>

        <div className="lg-heading">
          <h1>Welcome back</h1>
          <p>Sign in to manage restaurants, orders, offers, and AI activity.</p>
        </div>

        {error ? (
          <div className="lg-error" role="alert">
            {error}
          </div>
        ) : null}

        <label className="field">
          <span>Email</span>
          <div className="lg-input">
            <Mail size={15} strokeWidth={2.1} />
            <input
              autoComplete="email"
              onChange={(event) => {
                setEmail(event.target.value);
                setError(null);
              }}
              placeholder="you@example.com"
              required
              type="email"
              value={email}
            />
          </div>
        </label>

        <label className="field">
          <span>Password</span>
          <div className="lg-input">
            <Lock size={15} strokeWidth={2.1} />
            <input
              autoComplete="current-password"
              onChange={(event) => {
                setPassword(event.target.value);
                setError(null);
              }}
              placeholder="Your password"
              required
              type={showPassword ? 'text' : 'password'}
              value={password}
            />
            <button
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              className="lg-input__toggle"
              onClick={() => setShowPassword((current) => !current)}
              type="button"
            >
              {showPassword ? (
                <EyeOff size={15} strokeWidth={2.1} />
              ) : (
                <Eye size={15} strokeWidth={2.1} />
              )}
            </button>
          </div>
        </label>

        <button className="primary-button lg-submit" disabled={submitting} type="submit">
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="lg-footnote">
          Access is limited to platform admins and restaurant owners.
        </p>
      </form>
    </div>
  );
}
