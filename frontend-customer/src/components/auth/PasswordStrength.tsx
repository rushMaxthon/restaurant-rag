/** Four cheap, legible signals. Deliberately not an entropy score — the bar is
 *  advice while typing, not a gate; the server still owns what it accepts. */
function scoreOf(password: string): number {
  if (!password) {
    return 0;
  }
  let score = 0;
  if (password.length >= 6) score += 1;
  if (password.length >= 10) score += 1;
  if (/[A-Z]/.test(password) && /[a-z]/.test(password)) score += 1;
  if (/\d/.test(password) || /[^A-Za-z0-9]/.test(password)) score += 1;
  return score;
}

const LABELS = ['', 'Weak', 'Fair', 'Good', 'Strong'];

/**
 * Sits under the new-password field and stays out of the way until there is
 * something to say: an empty field renders nothing rather than an empty track,
 * which would read as a fifth form control.
 */
export function PasswordStrength({ password }: { password: string }) {
  const score = scoreOf(password);

  if (!password) {
    return null;
  }

  return (
    <div className="auth-strength" data-score={score}>
      <div aria-hidden="true" className="auth-strength__track">
        {[1, 2, 3, 4].map((step) => (
          <span
            key={step}
            className={
              step <= score ? 'auth-strength__bar auth-strength__bar--on' : 'auth-strength__bar'
            }
          />
        ))}
      </div>
      <span className="auth-strength__label">{LABELS[score]}</span>
    </div>
  );
}
