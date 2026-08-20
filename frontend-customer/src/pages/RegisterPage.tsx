import {useState} from 'react';
import {AuthShell} from '../components/AuthShell';
import {ApiError, api} from '../services/api';
import {useAppStore} from '../hooks/useAppStore';

interface RegisterPageProps {
  onNavigate: (path: string) => void;
}

type RegisterErrors = {
  fullName?: string;
  email?: string;
  password?: string;
  confirmPassword?: string;
};

function validateEmail(email: string): boolean {
  return /\S+@\S+\.\S+/.test(email);
}

export function RegisterPage({onNavigate}: RegisterPageProps) {
  const {consumePendingAuthRedirectPath, pushToast, setSession} = useAppStore();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState<RegisterErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const nextErrors: RegisterErrors = {};
    if (fullName.trim().length < 2) {
      nextErrors.fullName = 'Enter your full name.';
    }
    if (!email.trim()) {
      nextErrors.email = 'Enter your email address.';
    } else if (!validateEmail(email.trim())) {
      nextErrors.email = 'Enter a valid email address.';
    }
    if (password.length < 6) {
      nextErrors.password = 'Use at least 6 characters.';
    }
    if (!confirmPassword) {
      nextErrors.confirmPassword = 'Confirm your password.';
    } else if (confirmPassword !== password) {
      nextErrors.confirmPassword = 'Passwords do not match.';
    }

    setErrors(nextErrors);
    setApiError(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.register({
        full_name: fullName.trim(),
        email: email.trim(),
        password,
      });
      await setSession(response.access_token, response.user);
      pushToast(
        'Account created',
        'You can now browse, chat, and place orders.',
        'success',
      );
      onNavigate(consumePendingAuthRedirectPath() ?? '/');
    } catch (error: unknown) {
      setApiError(
        error instanceof ApiError
          ? error.message
          : 'Unable to create your account.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      eyebrow="Create Account"
      footerActionLabel="Login"
      footerPrompt="Already have an account?"
      onFooterAction={() => onNavigate('/auth/login')}
      subtitle="Create your account once and keep every reorder, recommendation, and delivery detail in sync."
      title="Start ordering smarter"
      errorMessage={apiError}>
      <form className="auth-form" noValidate onSubmit={submit}>
        <label className="auth-field">
          <span>Name</span>
          <input
            autoComplete="name"
            className={errors.fullName ? 'auth-input auth-input--error' : 'auth-input'}
            onChange={(event) => {
              setFullName(event.target.value);
              setErrors((current) => ({...current, fullName: undefined}));
              setApiError(null);
            }}
            placeholder="Enter your full name"
            type="text"
            value={fullName}
          />
          {errors.fullName ? (
            <small className="auth-error">{errors.fullName}</small>
          ) : null}
        </label>

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
            autoComplete="new-password"
            className={errors.password ? 'auth-input auth-input--error' : 'auth-input'}
            onChange={(event) => {
              setPassword(event.target.value);
              setErrors((current) => ({...current, password: undefined}));
              setApiError(null);
            }}
            placeholder="Create a password"
            type="password"
            value={password}
          />
          {errors.password ? (
            <small className="auth-error">{errors.password}</small>
          ) : null}
        </label>

        <label className="auth-field">
          <span>Confirm password</span>
          <input
            autoComplete="new-password"
            className={
              errors.confirmPassword ? 'auth-input auth-input--error' : 'auth-input'
            }
            onChange={(event) => {
              setConfirmPassword(event.target.value);
              setErrors((current) => ({
                ...current,
                confirmPassword: undefined,
              }));
              setApiError(null);
            }}
            placeholder="Confirm your password"
            type="password"
            value={confirmPassword}
          />
          {errors.confirmPassword ? (
            <small className="auth-error">{errors.confirmPassword}</small>
          ) : null}
        </label>

        <button className="auth-submit" disabled={submitting} type="submit">
          <span className="auth-submit__content">
            {submitting ? <span className="auth-spinner" aria-hidden="true" /> : null}
            <span>{submitting ? 'Creating account...' : 'Create Account'}</span>
          </span>
        </button>
      </form>
    </AuthShell>
  );
}
