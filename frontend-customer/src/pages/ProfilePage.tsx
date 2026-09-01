import { useCallback, useEffect, useMemo, useState } from 'react';
import { AppIcon, type IconName } from '../components/AppIcon';
import { ApiError, api, formatCurrency, formatDateTime } from '../services/api';
import { useAppStore } from '../hooks/useAppStore';
import type { Order, ProfileSummary } from '../types/app';

/** The same tones the Orders screen uses, so one order reads the same in both. */
function statusTone(status: Order['status']): { className: string; label: string } {
  if (status === 'DELIVERED') {
    return { className: 'status-pill status-pill--done', label: 'Delivered' };
  }
  if (status === 'PAYMENT_PENDING') {
    return { className: 'status-pill status-pill--pending', label: 'Payment pending' };
  }
  if (status === 'CANCELLED') {
    return { className: 'status-pill status-pill--cancelled', label: 'Cancelled' };
  }
  if (status === 'PREPARING' || status === 'OUT_FOR_DELIVERY') {
    return {
      className: 'status-pill status-pill--live',
      label: status === 'PREPARING' ? 'Preparing' : 'On the way',
    };
  }
  return { className: 'status-pill', label: status.replaceAll('_', ' ').toLowerCase() };
}

interface ProfilePageProps {
  token: string | null;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

export function ProfilePage({ token, onNavigate, onToast }: ProfilePageProps) {
  const { user, preferences, updateUser, logout } = useAppStore();
  const [profileSummary, setProfileSummary] = useState<ProfileSummary | null>(null);
  const [loading, setLoading] = useState(Boolean(token));
  const [refreshing, setRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const loadProfile = useCallback(async (options?: { silent?: boolean }) => {
    if (!token) {
      setProfileSummary(null);
      setErrorMessage(null);
      setLoading(false);
      setRefreshing(false);
      return;
    }

    if (options?.silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const summary = await api.getProfileSummary(token);
      setProfileSummary(summary);
      setErrorMessage(null);
      updateUser(summary.user);
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to load your account details.';
      setErrorMessage(message);
      onToast('Profile unavailable', message, 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [onToast, token, updateUser]);

  useEffect(() => {
    void loadProfile();
  }, [loadProfile]);

  const resolvedUser = profileSummary?.user ?? user;
  const resolvedPreferences = profileSummary?.preferences ?? preferences;
  const recentOrders = profileSummary?.recent_orders ?? [];
  const stats = profileSummary?.stats;

  const initials = resolvedUser?.full_name
    ? resolvedUser.full_name
        .split(/\s+/)
        .map((part) => part[0]?.toUpperCase())
        .filter(Boolean)
        .slice(0, 2)
        .join('')
    : 'CU';

  /* "Member since" is the one fact on this page the customer cannot see
     anywhere else in the app, and it is already on the record. */
  const memberSince = useMemo(() => {
    if (!resolvedUser?.created_at) {
      return null;
    }
    const parsed = new Date(resolvedUser.created_at);
    return Number.isNaN(parsed.getTime())
      ? null
      : new Intl.DateTimeFormat('en-IN', { month: 'long', year: 'numeric' }).format(parsed);
  }, [resolvedUser?.created_at]);

  const preferencesSummary = useMemo(() => {
    if (!resolvedPreferences) {
      return 'Set cuisines, spice, and budget preferences';
    }

    const parts = [
      resolvedPreferences.cuisines.slice(0, 2).join(', '),
      resolvedPreferences.diet === 'VEG'
        ? 'Veg'
        : resolvedPreferences.diet === 'NON_VEG'
          ? 'Non-Veg'
          : '',
      resolvedPreferences.budget === 'LOW'
        ? 'Low budget'
        : resolvedPreferences.budget === 'MID'
          ? 'Mid budget'
          : resolvedPreferences.budget === 'HIGH'
            ? 'High budget'
            : '',
    ].filter(Boolean);

    return parts.length > 0
      ? parts.join(' • ')
      : 'Set cuisines, spice, and budget preferences';
  }, [resolvedPreferences]);

  if (!token || !resolvedUser) {
    return (
      <div className="page-stack">
        <section className="hero-panel hero-panel--compact">
          <div className="hero-panel__copy">
            <span className="eyebrow">Your account</span>
            <h1>Keep your food world in one place.</h1>
            <p>
            Login to track orders, manage saved details, and keep your AI recommendations aligned with your tastes.
            </p>
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

  const navSections: Array<{
    group: string;
    links: Array<{ icon: IconName; label: string; hint: string; path: string }>;
  }> = [
    {
      group: 'Your account',
      links: [
        {
          icon: 'person',
          label: 'User details',
          hint: 'Name, phone, delivery address',
          path: '/profile/details',
        },
        {
          icon: 'receipt',
          label: 'Order history',
          hint: stats
            ? `${stats.total_orders} order${stats.total_orders === 1 ? '' : 's'}, ${stats.delivered_orders} delivered`
            : 'Every order and its status',
          path: '/profile/orders',
        },
        {
          icon: 'heart',
          label: 'Favorites',
          hint: stats
            ? `${stats.favorites_count} saved dish${stats.favorites_count === 1 ? '' : 'es'}`
            : 'Dishes you saved',
          path: '/favorites',
        },
      ],
    },
    {
      group: 'How the app behaves',
      links: [
        {
          icon: 'sparkles',
          label: 'Taste preferences',
          hint: preferencesSummary,
          path: '/profile/preferences',
        },
        {
          icon: 'sun',
          label: 'Appearance',
          hint: 'Light, dark, or follow your device',
          path: '/profile/appearance',
        },
        {
          icon: 'settings',
          label: 'Settings',
          hint: 'Notifications and privacy',
          path: '/profile/settings',
        },
        {
          icon: 'help',
          label: 'Help & support',
          hint: 'Answers, or ask the AI concierge',
          path: '/profile/help',
        },
      ],
    },
  ];

  const statTiles = [
    { label: 'Orders', value: stats?.total_orders },
    { label: 'Delivered', value: stats?.delivered_orders },
    { label: 'Favorites', value: stats?.favorites_count },
    { label: 'Saved places', value: stats?.saved_places },
  ];

  return (
    <div className="page-stack profile-page">
      {/* --- who you are ---------------------------------------------------
          The header carries identity and the four numbers that describe this
          account. They used to be rows in a label-and-value list below, where
          a count reads as a field to be edited rather than a figure. */}
      <section className="profile-hero">
        <div className="profile-hero__identity">
          <div className="profile-avatar">{initials}</div>
          <div className="profile-hero__copy">
            <h1>{resolvedUser.full_name}</h1>
            <p>{resolvedUser.email}</p>
            <div className="profile-hero__chips">
              {resolvedUser.is_verified ? (
                <span className="micro-chip micro-chip--verified">
                  <AppIcon name="check" size={12} /> Verified
                </span>
              ) : (
                <span className="micro-chip">Not verified</span>
              )}
              {memberSince ? <span className="micro-chip">Member since {memberSince}</span> : null}
            </div>
          </div>
        </div>

        <div className="profile-hero__actions">
          <button
            className="primary-button profile-hero__edit"
            onClick={() => onNavigate('/profile/details')}
            type="button"
          >
            Edit profile
          </button>
          <button
            aria-label="Refresh profile"
            className="profile-hero__refresh"
            disabled={loading || refreshing}
            onClick={() => {
              void loadProfile({ silent: true });
            }}
            title={refreshing ? 'Refreshing…' : 'Refresh'}
            type="button"
          >
            <AppIcon name="refresh" size={17} />
          </button>
        </div>

        <div className="profile-stats">
          {statTiles.map((tile) => (
            <div className="profile-stat" key={tile.label}>
              <strong>{tile.value ?? '—'}</strong>
              <span>{tile.label}</span>
            </div>
          ))}
        </div>
      </section>

      {errorMessage ? (
        <div className="empty-inline profile-page__sync">
          <strong>Profile sync delayed</strong>
          <span>{errorMessage}</span>
          <button className="text-link" onClick={() => void loadProfile()} type="button">
            Try again
          </button>
        </div>
      ) : null}

      <div className="profile-columns">
        {/* --- the details, minus what the header already said -------------- */}
        <section className="section-card profile-details-card">
          <div className="section-card__header">
            <div>
              <span className="eyebrow">Details</span>
              <h2>Where your orders go</h2>
            </div>
            <button className="text-link" onClick={() => onNavigate('/profile/details')} type="button">
              Edit
            </button>
          </div>
          <div className="profile-field">
            <span className="profile-field__label">
              <AppIcon name="phone" size={15} /> Phone
            </span>
            {resolvedUser.phone_number ? (
              <strong>{resolvedUser.phone_number}</strong>
            ) : (
              <button className="profile-field__add" onClick={() => onNavigate('/profile/details')} type="button">
                Add a number
              </button>
            )}
          </div>
          <div className="profile-field">
            <span className="profile-field__label">
              <AppIcon name="location" size={15} /> Default address
            </span>
            {resolvedUser.default_address ? (
              <strong>{resolvedUser.default_address}</strong>
            ) : (
              <button className="profile-field__add" onClick={() => onNavigate('/profile/details')} type="button">
                Add an address
              </button>
            )}
          </div>
          <div className="profile-field">
            <span className="profile-field__label">
              <AppIcon name="mail" size={15} /> Email
            </span>
            <strong>{resolvedUser.email}</strong>
          </div>
        </section>

        {/* --- everywhere else you can go ---------------------------------- */}
        <section className="section-card profile-nav-card">
          {navSections.map((section) => (
            <div className="profile-nav-group" key={section.group}>
              <span className="eyebrow">{section.group}</span>
              <div className="profile-nav">
                {section.links.map((link) => (
                  <button
                    className="profile-nav-row"
                    key={link.path}
                    onClick={() => onNavigate(link.path)}
                    type="button"
                  >
                    <span className="profile-nav-row__icon">
                      <AppIcon name={link.icon} size={18} />
                    </span>
                    <span className="profile-nav-row__copy">
                      <strong>{link.label}</strong>
                      <small>{link.hint}</small>
                    </span>
                    <AppIcon className="profile-nav-row__chevron" name="chevron-right" size={16} />
                  </button>
                ))}
              </div>
            </div>
          ))}

          <button
            className="profile-logout"
            onClick={() => {
              logout();
              onToast('Signed out', 'See you again soon.', 'info');
              onNavigate('/');
            }}
            type="button"
          >
            <AppIcon name="logout" size={17} />
            Log out
          </button>
        </section>
      </div>

      {/* --- the last few orders ------------------------------------------ */}
      <section className="section-card profile-orders-card">
        <div className="section-card__header">
          <div>
            <span className="eyebrow">Recent</span>
            <h2>Your last orders</h2>
          </div>
          <button className="text-link" onClick={() => onNavigate('/profile/orders')} type="button">
            Open full history
          </button>
        </div>
        {loading ? (
          <div className="profile-order-list">
            {Array.from({ length: 3 }).map((_, index) => (
              <div className="profile-order-row profile-order-row--skeleton" key={index} />
            ))}
          </div>
        ) : recentOrders.length > 0 ? (
          <div className="profile-order-list">
            {recentOrders.map((order) => {
              const tone = statusTone(order.status);
              const itemCount = order.items.reduce((count, item) => count + item.quantity, 0);
              return (
                <button
                  className="profile-order-row"
                  key={order.id}
                  onClick={() => onNavigate(`/orders/${order.id}`)}
                  type="button"
                >
                  <span className="profile-order-row__mark">
                    <AppIcon name="receipt" size={17} />
                  </span>
                  <span className="profile-order-row__copy">
                    <strong>{order.restaurant.name}</strong>
                    {/* The name and the date used to be adjacent inline
                        elements with no separator, and rendered as
                        "Dragon Wok14 Aug 2026". */}
                    <small>
                      {formatDateTime(order.placed_at)} · {itemCount} item{itemCount === 1 ? '' : 's'}
                    </small>
                  </span>
                  <span className="profile-order-row__end">
                    <strong>{formatCurrency(order.total_amount)}</strong>
                    <span className={tone.className}>{tone.label}</span>
                  </span>
                </button>
              );
            })}
          </div>
        ) : errorMessage ? (
          <div className="empty-state">
            <strong>We could not refresh your recent orders.</strong>
            <span>{errorMessage}</span>
            <button className="secondary-button" onClick={() => void loadProfile()} type="button">
              Try again
            </button>
          </div>
        ) : (
          <div className="empty-state">
            <strong>No orders yet.</strong>
            <span>Place your first order and it will show up here.</span>
            <button className="primary-button" onClick={() => onNavigate('/menu')} type="button">
              Browse the menu
            </button>
          </div>
        )}
      </section>
    </div>
  );
}
