import {
  Bot,
  LogOut,
  Mail,
  RotateCcw,
  Shield,
  SlidersHorizontal,
  Store,
  TriangleAlert,
  UserRound,
} from 'lucide-react';
import { useState } from 'react';
import { PageIntro } from '../components/PageIntro';
import { useAdminStore } from '../hooks/useAdminStore';
import {
  DEFAULT_WORKSPACE_SETTINGS,
  clearWorkspaceSettings,
  readWorkspaceSettings,
  writeWorkspaceSettings,
  type WorkspaceSettings,
} from '../services/workspaceSettings';

interface SettingsPageProps {
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

const TOGGLE_ROWS: Array<{
  key: keyof WorkspaceSettings;
  group: 'operations' | 'experience';
  label: string;
  description: string;
  icon: typeof Shield;
}> = [
  {
    key: 'maintenanceBanner',
    group: 'operations',
    label: 'Maintenance banner',
    description:
      'Shows a live maintenance notice at the top of this workspace for admins and owners.',
    icon: TriangleAlert,
  },
  {
    key: 'strictModeration',
    group: 'operations',
    label: 'Strict moderation',
    description: 'Surface flagged reviews and restaurant approval risks more aggressively.',
    icon: Shield,
  },
  {
    key: 'aiFallbacks',
    group: 'experience',
    label: 'AI fallback replies',
    description: 'Allow the RAG system to return safe suggestion fallbacks on weak retrieval.',
    icon: Bot,
  },
  {
    key: 'compactDashboard',
    group: 'experience',
    label: 'Compact dashboard mode',
    description: 'Reduce visual density if you prefer a tighter operations workspace.',
    icon: SlidersHorizontal,
  },
];

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return '?';
  }
  const first = parts[0][0] ?? '';
  const last = parts.length > 1 ? (parts[parts.length - 1][0] ?? '') : '';
  return `${first}${last}`.toUpperCase();
}

export function SettingsPage({ onToast }: SettingsPageProps) {
  const { user, role, logout } = useAdminStore();
  const [settings, setSettings] = useState<WorkspaceSettings>(() =>
    readWorkspaceSettings(),
  );

  const toggle = (key: keyof WorkspaceSettings) => {
    const next = { ...settings, [key]: !settings[key] };
    setSettings(next);
    writeWorkspaceSettings(next);
    onToast('Settings updated', 'Workspace preferences saved on this device.', 'success');
  };

  const resetPreferences = () => {
    clearWorkspaceSettings();
    setSettings(DEFAULT_WORKSPACE_SETTINGS);
    onToast('Preferences reset', 'Workspace preferences restored to their defaults.', 'info');
  };

  const roleLabel = role === 'ADMIN' ? 'Platform Admin' : 'Restaurant Owner';

  const renderRows = (group: 'operations' | 'experience') =>
    TOGGLE_ROWS.filter(row => row.group === group).map(row => {
      const Icon = row.icon;
      const isOn = settings[row.key];
      return (
        <button
          aria-pressed={isOn}
          className="st-row"
          key={row.key}
          onClick={() => toggle(row.key)}
          type="button"
        >
          <span className="st-row__icon">
            <Icon size={15} strokeWidth={2.1} />
          </span>
          <span className="st-row__copy">
            <strong>{row.label}</strong>
            <span>{row.description}</span>
          </span>
          <span className={isOn ? 'st-switch st-switch--on' : 'st-switch'}>
            <span className="st-switch__thumb" />
          </span>
        </button>
      );
    });

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="System"
        title="Workspace settings"
        description="Your account, session scope, and local workspace preferences in one place."
      />

      <section className="st-layout">
        <section className="admin-surface st-card st-account">
          <header className="st-card__header">
            <span className="st-card__icon">
              <UserRound size={16} strokeWidth={2.1} />
            </span>
            <div>
              <h2>Account</h2>
              <p>The session currently signed in to this workspace.</p>
            </div>
          </header>

          {user ? (
            <div className="st-account__body">
              <div className="st-account__identity">
                <span
                  className={`st-avatar st-avatar--${(role ?? 'ADMIN').toLowerCase()}`}
                >
                  {getInitials(user.full_name)}
                </span>
                <div className="st-account__copy">
                  <strong>{user.full_name}</strong>
                  <span
                    className={`st-role-pill st-role-pill--${(role ?? 'ADMIN').toLowerCase()}`}
                  >
                    {role === 'ADMIN' ? (
                      <Shield size={12} strokeWidth={2.2} />
                    ) : (
                      <Store size={12} strokeWidth={2.2} />
                    )}
                    {roleLabel}
                  </span>
                </div>
              </div>

              <div className="st-account__facts">
                <div className="st-account__fact">
                  <span>Email</span>
                  <strong className="st-account__fact-inline">
                    <Mail size={13} strokeWidth={2.1} />
                    {user.email}
                  </strong>
                </div>
                <div className="st-account__fact">
                  <span>Access scope</span>
                  <strong>
                    {role === 'ADMIN'
                      ? 'Platform-wide: every restaurant, user, and report.'
                      : 'Restricted to your assigned restaurant and its branches.'}
                  </strong>
                </div>
              </div>

              <button className="secondary-button st-signout" onClick={logout} type="button">
                <LogOut size={15} strokeWidth={2.1} />
                Sign out of this session
              </button>
            </div>
          ) : null}
        </section>

        <div className="st-stack">
          <section className="admin-surface st-card">
            <header className="st-card__header">
              <span className="st-card__icon">
                <Shield size={16} strokeWidth={2.1} />
              </span>
              <div>
                <h2>Operations</h2>
                <p>Control panel defaults for day-to-day moderation.</p>
              </div>
            </header>
            <div className="st-rows">{renderRows('operations')}</div>
          </section>

          <section className="admin-surface st-card">
            <header className="st-card__header">
              <span className="st-card__icon">
                <Bot size={16} strokeWidth={2.1} />
              </span>
              <div>
                <h2>AI & experience</h2>
                <p>Assistant behavior and workspace density preferences.</p>
              </div>
            </header>
            <div className="st-rows">{renderRows('experience')}</div>
          </section>

          <section className="admin-surface st-card st-danger-zone">
            <header className="st-card__header">
              <span className="st-card__icon st-card__icon--muted">
                <RotateCcw size={16} strokeWidth={2.1} />
              </span>
              <div>
                <h2>Reset preferences</h2>
                <p>
                  Restore every workspace preference on this device to its default value.
                  Your account and data are not affected.
                </p>
              </div>
              <button className="secondary-button" onClick={resetPreferences} type="button">
                Reset to defaults
              </button>
            </header>
          </section>
        </div>
      </section>
    </div>
  );
}
