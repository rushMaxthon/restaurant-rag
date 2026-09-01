import type { PropsWithChildren } from 'react';
import { AppIcon, type IconName } from './AppIcon';
import { useAppConfig } from '../store/useAppConfig';

type AuthMode = 'login' | 'register';

interface AuthShellProps extends PropsWithChildren {
  mode: AuthMode;
  title: string;
  subtitle: string;
  /** Switches to the other screen. The shell owns both the tab and the footer. */
  onSwitchMode: () => void;
  /** Leaves the flow entirely — the customer can browse without an account. */
  onDismiss?: () => void;
  errorMessage?: string | null;
}

/** What an account actually buys you here. Concrete, not marketing copy. */
const BENEFITS: Array<{ icon: IconName; title: string; text: string }> = [
  {
    icon: 'sparkles',
    title: 'Picks that learn your taste',
    text: 'The menu reorders itself around what you actually order.',
  },
  {
    icon: 'ticket',
    title: 'Offers matched to you',
    text: 'Deals unlock automatically the moment your cart qualifies.',
  },
  {
    icon: 'receipt',
    title: 'Reorder in two taps',
    text: 'Past orders, saved addresses and live status in one place.',
  },
];

const TABS: Array<{ mode: AuthMode; label: string }> = [
  { mode: 'login', label: 'Log in' },
  { mode: 'register', label: 'Sign up' },
];

const FOOTER: Record<AuthMode, { prompt: string; action: string }> = {
  login: { prompt: "Don't have an account?", action: 'Create one' },
  register: { prompt: 'Already have an account?', action: 'Log in' },
};

/**
 * The signed-out doorway.
 *
 * Two panels: the restaurant on the left, the form on the right. The brand comes
 * from `/app-config`, so this screen says the same name as the sign the customer
 * walked past.
 *
 * Login and sign-up are one composition with a segmented switch rather than two
 * pages joined by a link at the bottom. Someone who lands on the wrong one sees
 * the way across before they have read the form, and the panel does not appear
 * to reload when they take it.
 *
 * Below the site breakpoint the aside collapses and the form leads, because on
 * a phone this is a step in a flow rather than a landing page.
 */
export function AuthShell({
  mode,
  title,
  subtitle,
  onSwitchMode,
  onDismiss,
  errorMessage,
  children,
}: AuthShellProps) {
  const { displayName } = useAppConfig();
  const initials = displayName.slice(0, 2).toUpperCase();
  const footer = FOOTER[mode];

  return (
    <section className={`auth-shell auth-shell--${mode}`}>
      <aside className="auth-aside">
        <span aria-hidden="true" className="auth-aside__glow auth-aside__glow--one" />
        <span aria-hidden="true" className="auth-aside__glow auth-aside__glow--two" />

        <div className="auth-aside__brand">
          <span className="auth-mark auth-mark--lg">{initials}</span>
          <span className="auth-aside__name">{displayName}</span>
        </div>

        <h2 className="auth-aside__headline">
          Your table, your usual, <em>ready when you are.</em>
        </h2>

        <ul className="auth-benefits">
          {BENEFITS.map((benefit) => (
            <li key={benefit.title}>
              <span className="auth-benefits__icon">
                <AppIcon name={benefit.icon} size={18} />
              </span>
              <span className="auth-benefits__copy">
                <strong>{benefit.title}</strong>
                <small>{benefit.text}</small>
              </span>
            </li>
          ))}
        </ul>

        <p className="auth-aside__footnote">
          <AppIcon name="shield" size={15} />
          One account works here and in the {displayName} app.
        </p>
      </aside>

      <div className="auth-panel">
        <div className="auth-panel__top">
          <div className="auth-brand">
            <span className="auth-mark">{initials}</span>
            <div className="auth-brand__copy">
              <strong>{displayName}</strong>
              <span>Order online for delivery or pickup</span>
            </div>
          </div>

          {onDismiss ? (
            <button className="auth-skip" onClick={onDismiss} type="button">
              Browse first
              <AppIcon name="arrow-forward" size={15} />
            </button>
          ) : null}
        </div>

        {/* Navigation, not a tab set: each half is a route, so `aria-current`
            is the honest annotation and there is no panel to control. */}
        <nav aria-label="Account" className="auth-tabs">
          {TABS.map((tab) => (
            <button
              key={tab.mode}
              aria-current={tab.mode === mode ? 'page' : undefined}
              className={
                tab.mode === mode ? 'auth-tabs__tab auth-tabs__tab--active' : 'auth-tabs__tab'
              }
              onClick={tab.mode === mode ? undefined : onSwitchMode}
              type="button"
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <header className="auth-panel__header">
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </header>

        {errorMessage ? (
          <div className="auth-alert" role="alert">
            <span className="auth-alert__icon">
              <AppIcon name="close" size={14} />
            </span>
            <span>{errorMessage}</span>
          </div>
        ) : null}

        <div className="auth-form-stack">{children}</div>

        <p className="auth-switch">
          {footer.prompt}{' '}
          <button className="auth-switch__link" onClick={onSwitchMode} type="button">
            {footer.action}
          </button>
        </p>
      </div>
    </section>
  );
}
