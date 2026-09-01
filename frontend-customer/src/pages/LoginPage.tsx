import { useState } from 'react';
import { AuthShell } from '../components/AuthShell';
import { AuthField } from '../components/auth/AuthField';
import { ApiError, api } from '../services/api';
import { useAppStore } from '../hooks/useAppStore';

interface LoginPageProps {
  onNavigate: (path: string) => void;
}

type LoginErrors = {
  email?: string;
  password?: string;
};

function validateEmail(email: string): boolean {
  return /\S+@\S+\.\S+/.test(email);
}

export function LoginPage({ onNavigate }: LoginPageProps) {
  const { consumePendingAuthRedirectPath, pushToast, setSession } = useAppStore();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<LoginErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  /** Every field clears its own error and the banner as soon as it is edited,
   *  so the form stops accusing the customer of a mistake they are fixing. */
  const edit = <K extends keyof LoginErrors>(field: K, apply: (value: string) => void) =>
    (value: string) => {
      apply(value);
      setErrors((current) => ({ ...current, [field]: undefined }));
      setApiError(null);
    };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const nextErrors: LoginErrors = {};
    if (!email.trim()) {
      nextErrors.email = 'Enter your email address.';
    } else if (!validateEmail(email.trim())) {
      nextErrors.email = 'Enter a valid email address.';
    }
    if (!password.trim()) {
      nextErrors.password = 'Enter your password.';
    }

    setErrors(nextErrors);
    setApiError(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.login({
        email: email.trim(),
        password,
      });
      if (response.user.role !== 'CUSTOMER') {
        throw new ApiError('Admin/Owner accounts cannot access the customer app.', 403);
      }
      await setSession(response.access_token, response.user);
      pushToast('Welcome back', 'Your personalized feed is ready.', 'success');
      onNavigate(consumePendingAuthRedirectPath() ?? '/');
    } catch (error: unknown) {
      setApiError(error instanceof ApiError ? error.message : 'Unable to log you in.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      errorMessage={apiError}
      mode="login"
      onDismiss={() => onNavigate('/')}
      onSwitchMode={() => onNavigate('/auth/register')}
      subtitle="Pick up where you left off — saved addresses, smarter suggestions and one-tap checkout."
      title="Welcome back"
    >
      <form className="auth-form" noValidate onSubmit={submit}>
        <AuthField
          autoComplete="email"
          error={errors.email}
          icon="mail"
          label="Email"
          onChange={edit('email', setEmail)}
          placeholder="you@example.com"
          type="email"
          value={email}
        />

        <AuthField
          autoComplete="current-password"
          error={errors.password}
          icon="lock"
          label="Password"
          onChange={edit('password', setPassword)}
          placeholder="Enter your password"
          type="password"
          value={password}
        />

        <button className="auth-submit" disabled={submitting} type="submit">
          <span className="auth-submit__content">
            {submitting ? <span aria-hidden="true" className="auth-spinner" /> : null}
            <span>{submitting ? 'Logging in…' : 'Log in'}</span>
          </span>
        </button>
      </form>
    </AuthShell>
  );
}
