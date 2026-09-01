import { useState } from 'react';
import { AuthShell } from '../components/AuthShell';
import { AuthField } from '../components/auth/AuthField';
import { PasswordStrength } from '../components/auth/PasswordStrength';
import { ApiError, api } from '../services/api';
import { useAppStore } from '../hooks/useAppStore';

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

export function RegisterPage({ onNavigate }: RegisterPageProps) {
  const { consumePendingAuthRedirectPath, pushToast, setSession } = useAppStore();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState<RegisterErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  /** Every field clears its own error and the banner as soon as it is edited,
   *  so the form stops accusing the customer of a mistake they are fixing. */
  const edit = <K extends keyof RegisterErrors>(field: K, apply: (value: string) => void) =>
    (value: string) => {
      apply(value);
      setErrors((current) => ({ ...current, [field]: undefined }));
      setApiError(null);
    };

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
      pushToast('Account created', 'You can now browse, chat, and place orders.', 'success');
      onNavigate(consumePendingAuthRedirectPath() ?? '/');
    } catch (error: unknown) {
      setApiError(
        error instanceof ApiError ? error.message : 'Unable to create your account.',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell
      errorMessage={apiError}
      mode="register"
      onDismiss={() => onNavigate('/')}
      onSwitchMode={() => onNavigate('/auth/login')}
      subtitle="Reorders, recommendations and addresses, all kept in sync."
      title="Start ordering smarter"
    >
      <form className="auth-form" noValidate onSubmit={submit}>
        <AuthField
          autoComplete="name"
          error={errors.fullName}
          icon="person"
          label="Full name"
          onChange={edit('fullName', setFullName)}
          placeholder="Enter your full name"
          type="text"
          value={fullName}
        />

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

        {/* The two passwords share a row. They are the only pair on this form
            that is short enough to read at half width, and pairing them is what
            keeps the submit button above the fold on a phone. */}
        <div className="auth-row">
          <AuthField
            autoComplete="new-password"
            error={errors.password}
            icon="lock"
            label="Password"
            onChange={edit('password', setPassword)}
            placeholder="6+ characters"
            type="password"
            value={password}
          >
            <PasswordStrength password={password} />
          </AuthField>

          <AuthField
            autoComplete="new-password"
            error={errors.confirmPassword}
            icon="lock"
            label="Confirm"
            onChange={edit('confirmPassword', setConfirmPassword)}
            placeholder="Repeat it"
            type="password"
            value={confirmPassword}
          />
        </div>

        <button className="auth-submit" disabled={submitting} type="submit">
          <span className="auth-submit__content">
            {submitting ? <span aria-hidden="true" className="auth-spinner" /> : null}
            <span>{submitting ? 'Creating account…' : 'Create account'}</span>
          </span>
        </button>

        <p className="auth-legal">
          By continuing you agree to our terms and privacy policy.
        </p>
      </form>
    </AuthShell>
  );
}
