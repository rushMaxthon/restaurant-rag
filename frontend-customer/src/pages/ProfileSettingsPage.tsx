import { useEffect, useState } from 'react';

interface ProfileSettingsPageProps {
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

type SettingsState = {
  orderUpdates: boolean;
  aiSuggestions: boolean;
  privateRecommendations: boolean;
  compactMode: boolean;
};

const SETTINGS_KEY = 'restaurant-rag-customer-settings';
const defaultSettings: SettingsState = {
  orderUpdates: true,
  aiSuggestions: true,
  privateRecommendations: false,
  compactMode: false,
};

export function ProfileSettingsPage({ token, onNavigate, onToast }: ProfileSettingsPageProps) {
  const [settings, setSettings] = useState<SettingsState>(defaultSettings);

  useEffect(() => {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) {
      return;
    }

    try {
      const parsed = JSON.parse(raw) as Partial<SettingsState>;
      setSettings({ ...defaultSettings, ...parsed });
    } catch {
      window.localStorage.removeItem(SETTINGS_KEY);
    }
  }, []);

  if (!token) {
    return (
      <div className="page-stack">
        <section className="hero-panel hero-panel--compact">
          <div className="hero-panel__copy">
            <span className="eyebrow">Settings</span>
            <h1>Login to manage your preferences.</h1>
            <p>Keep notifications, privacy, and recommendation controls inside your profile where they belong.</p>
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

  const updateSetting = (key: keyof SettingsState) => {
    const next = {
      ...settings,
      [key]: !settings[key],
    };
    setSettings(next);
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(next));
    onToast('Settings saved', 'Your preference has been updated locally.', 'success');
  };

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel--compact">
        <div className="hero-panel__copy">
          <span className="eyebrow">Settings</span>
          <h1>Fine-tune your delivery and discovery flow.</h1>
          <p>Manage updates, privacy, and how much AI guidance you want while keeping the same warm app experience.</p>
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
              <span className="eyebrow">Notifications</span>
              <h2>Stay in the loop</h2>
            </div>
          </div>
          <div className="settings-list">
            <button className="settings-row" onClick={() => updateSetting('orderUpdates')} type="button">
              <div>
                <strong>Order updates</strong>
                <span>Get delivery progress updates and checkout confirmations.</span>
              </div>
              <span className={settings.orderUpdates ? 'toggle-pill toggle-pill--on' : 'toggle-pill'}>{settings.orderUpdates ? 'On' : 'Off'}</span>
            </button>
            <button className="settings-row" onClick={() => updateSetting('aiSuggestions')} type="button">
              <div>
                <strong>AI suggestions</strong>
                <span>Receive chat-led meal tips, offers, and personalized discovery prompts.</span>
              </div>
              <span className={settings.aiSuggestions ? 'toggle-pill toggle-pill--on' : 'toggle-pill'}>{settings.aiSuggestions ? 'On' : 'Off'}</span>
            </button>
          </div>
        </article>

        <article className="section-card">
          <div className="section-card__header">
            <div>
              <span className="eyebrow">Privacy & display</span>
              <h2>Control your experience</h2>
            </div>
          </div>
          <div className="settings-list">
            <button className="settings-row" onClick={() => updateSetting('privateRecommendations')} type="button">
              <div>
                <strong>Private recommendations</strong>
                <span>Keep recommendations based only on your current session activity.</span>
              </div>
              <span className={settings.privateRecommendations ? 'toggle-pill toggle-pill--on' : 'toggle-pill'}>{settings.privateRecommendations ? 'On' : 'Off'}</span>
            </button>
            <button className="settings-row" onClick={() => updateSetting('compactMode')} type="button">
              <div>
                <strong>Compact cards</strong>
                <span>Reduce content density in lists when you want a tighter browsing layout.</span>
              </div>
              <span className={settings.compactMode ? 'toggle-pill toggle-pill--on' : 'toggle-pill'}>{settings.compactMode ? 'On' : 'Off'}</span>
            </button>
          </div>
        </article>
      </section>
    </div>
  );
}
