interface ProfileHelpPageProps {
  token: string | null;
  onNavigate: (path: string) => void;
}

export function ProfileHelpPage({ token, onNavigate }: ProfileHelpPageProps) {
  if (!token) {
    return (
      <div className="page-stack">
        <section className="hero-panel hero-panel--compact">
          <div className="hero-panel__copy">
            <span className="eyebrow">Help & support</span>
            <h1>Login to unlock support tools.</h1>
            <p>Access order help, chat guidance, and customer account support from one profile-based support space.</p>
            <div className="hero-panel__actions">
              <button className="primary-button" onClick={() => onNavigate('/auth/login')} type="button">
                Login
              </button>
              <button className="secondary-button" onClick={() => onNavigate('/auth/register')} type="button">
                Create account
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel--compact">
        <div className="hero-panel__copy">
          <span className="eyebrow">Help & support</span>
          <h1>Get unstuck without leaving profile.</h1>
          <p>Find quick help for orders, payments, AI suggestions, and your account settings in one calm support hub.</p>
          <div className="profile-subnav">
            <button className="secondary-button" onClick={() => onNavigate('/profile')} type="button">
              Back to profile
            </button>
          </div>
        </div>
      </section>

      <section className="profile-settings-grid">
        <article className="section-card">
          <div className="section-card__header">
            <div>
              <span className="eyebrow">Support options</span>
              <h2>How can we help?</h2>
            </div>
          </div>
          <div className="settings-list">
            <button className="settings-row" onClick={() => onNavigate('/profile/orders')} type="button">
              <div>
                <strong>Track or review an order</strong>
                <span>Open your order history and check live delivery steps or past totals.</span>
              </div>
              <span className="settings-row__chevron">→</span>
            </button>
            <button className="settings-row" onClick={() => onNavigate('/chat')} type="button">
              <div>
                <strong>Ask the AI concierge</strong>
                <span>Get help with dish discovery, budgets, and alternative suggestions from the chat assistant.</span>
              </div>
              <span className="settings-row__chevron">→</span>
            </button>
          </div>
        </article>

        <article className="section-card">
          <div className="section-card__header">
            <div>
              <span className="eyebrow">FAQs</span>
              <h2>Quick answers</h2>
            </div>
          </div>
          <div className="faq-list">
            <article className="faq-card">
              <strong>How do I update my saved address?</strong>
              <span>Open Profile → User Details and update the default address field.</span>
            </article>
            <article className="faq-card">
              <strong>Where can I see my previous orders?</strong>
              <span>Profile → Order History keeps your full order timeline and delivery statuses together.</span>
            </article>
            <article className="faq-card">
              <strong>Can I turn off AI suggestions?</strong>
              <span>Yes. Open Profile → Settings and disable AI suggestions whenever you want a quieter experience.</span>
            </article>
          </div>
        </article>
      </section>
    </div>
  );
}
