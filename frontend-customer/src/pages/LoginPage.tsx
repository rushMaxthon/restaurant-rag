import {useState} from 'react';
import {AuthShell} from '../components/AuthShell';
import {ApiError, api} from '../services/api';
import {useAppStore} from '../hooks/useAppStore';

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

export function LoginPage({onNavigate}: LoginPageProps) {
  const {consumePendingAuthRedirectPath, pushToast, setSession} = useAppStore();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<LoginErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
        throw new ApiError(
          'Admin/Owner accounts cannot access the customer app.',
          403,
        );
      }
      await setSession(response.access_token, response.user);
      pushToast('Welcome back', 'Your personalized feed is ready.', 'success');
      onNavigate(consumePendingAuthRedirectPath() ?? '/');
    } catch (error: unknown) {
      setApiError(
        error instanceof ApiError ? error.message : 'Unable to log you in.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      eyebrow="Welcome Back"
      footerActionLabel="Sign up"
      footerPrompt="Don't have an account?"
      onFooterAction={() => onNavigate('/auth/register')}
      subtitle="Login to continue with saved addresses, smarter suggestions, and quick checkout."
      title="Fast login for your next craving"
      errorMessage={apiError}>
      <form className="auth-form" noValidate onSubmit={submit}>
        <label className="auth-field">
          <span>Email</span>
          <input
            autoComplete="email"
            className={errors.email ? 'auth-input auth-input--error' : 'auth-input'}
            onChange={(event) => {
              setEmail(event.target.value);
              setErrors((current) => ({...current, email: undefined}));
              setApiError(null);
            }}
            placeholder="Enter your email"
            type="email"
            value={email}
          />
          {errors.email ? <small className="auth-error">{errors.email}</small> : null}
        </label>

        <label className="auth-field">
          <span>Password</span>
          <input
            autoComplete="current-password"
            className={errors.password ? 'auth-input auth-input--error' : 'auth-input'}
            onChange={(event) => {
              setPassword(event.target.value);
              setErrors((current) => ({...current, password: undefined}));
              setApiError(null);
            }}
            placeholder="Enter your password"
            type="password"
            value={password}
          />
          {errors.password ? (
            <small className="auth-error">{errors.password}</small>
          ) : null}
        </label>

        <button className="auth-submit" disabled={submitting} type="submit">
          <span className="auth-submit__content">
            {submitting ? <span className="auth-spinner" aria-hidden="true" /> : null}
            <span>{submitting ? 'Logging in...' : 'Login'}</span>
          </span>
        </button>
      </form>
    </AuthShell>
  );
}
