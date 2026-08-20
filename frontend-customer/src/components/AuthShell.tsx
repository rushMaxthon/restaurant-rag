import type { PropsWithChildren } from 'react';

interface AuthShellProps extends PropsWithChildren {
  eyebrow: string;
  title: string;
  subtitle: string;
  footerPrompt: string;
  footerActionLabel: string;
  onFooterAction: () => void;
  errorMessage?: string | null;
}

export function AuthShell({
  eyebrow,
  title,
  subtitle,
  footerPrompt,
  footerActionLabel,
  onFooterAction,
  errorMessage,
  children,
}: AuthShellProps) {
  return (
    <section className="auth-shell">
      <div className="auth-panel">
        <div className="auth-brand">
          <span className="auth-brand__mark">RR</span>
          <div className="auth-brand__copy">
            <strong>Restaurant RAG</strong>
            <span>Smarter cravings, faster checkout</span>
          </div>
        </div>

        <header className="auth-panel__header">
          <span className="eyebrow">{eyebrow}</span>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </header>

        {errorMessage ? (
          <div className="auth-alert" role="alert">
            {errorMessage}
          </div>
        ) : null}

        <div className="auth-form-stack">{children}</div>

        <div className="auth-switch">
          <span>{footerPrompt}</span>
          <button className="text-link" onClick={onFooterAction} type="button">
            {footerActionLabel}
          </button>
        </div>
      </div>
    </section>
  );
}
