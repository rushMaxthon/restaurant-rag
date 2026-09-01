import { useId, useState } from 'react';
import { AppIcon, type IconName } from '../AppIcon';

interface AuthFieldProps {
  label: string;
  icon: IconName;
  type: 'text' | 'email' | 'password';
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  autoComplete?: string;
  error?: string;
  children?: React.ReactNode;
}

/**
 * One row of the auth form.
 *
 * The label sits above the control rather than inside it as a placeholder that
 * vanishes on focus, so a half-filled form still says what each box is for. The
 * leading glyph is decorative — it gives the row a fixed optical start so the
 * fields stack into a column instead of four unrelated boxes.
 *
 * Password fields reveal themselves through the trailing button. Typing a
 * password blind is the single biggest source of failed sign-ins, and the toggle
 * costs one button.
 */
export function AuthField({
  label,
  icon,
  type,
  value,
  onChange,
  placeholder,
  autoComplete,
  error,
  children,
}: AuthFieldProps) {
  const id = useId();
  const [revealed, setRevealed] = useState(false);
  const isPassword = type === 'password';
  const inputType = isPassword && revealed ? 'text' : type;

  return (
    <div className={error ? 'auth-field auth-field--invalid' : 'auth-field'}>
      <label className="auth-field__label" htmlFor={id}>
        {label}
      </label>

      <div className="auth-control">
        <span aria-hidden="true" className="auth-control__icon">
          <AppIcon name={icon} size={18} />
        </span>

        <input
          aria-describedby={error ? `${id}-error` : undefined}
          aria-invalid={error ? true : undefined}
          autoComplete={autoComplete}
          className="auth-control__input"
          id={id}
          onChange={(event) => onChange(event.target.value)}
          placeholder={placeholder}
          type={inputType}
          value={value}
        />

        {isPassword ? (
          <button
            aria-label={revealed ? 'Hide password' : 'Show password'}
            aria-pressed={revealed}
            className="auth-control__reveal"
            onClick={() => setRevealed((current) => !current)}
            tabIndex={-1}
            type="button"
          >
            <AppIcon name={revealed ? 'eye-off' : 'eye'} size={18} />
          </button>
        ) : null}
      </div>

      {children}

      {error ? (
        <p className="auth-field__error" id={`${id}-error`}>
          <AppIcon name="close" size={13} />
          {error}
        </p>
      ) : null}
    </div>
  );
}
