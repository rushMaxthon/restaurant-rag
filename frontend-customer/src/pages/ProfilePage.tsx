import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, api, formatCurrency, formatDateTime } from '../services/api';
import { useAppStore } from '../hooks/useAppStore';
import type { ProfileSummary } from '../types/app';

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

  return (
    <div className="page-stack">
      <section className="hero-panel hero-panel--profile">
        <div className="profile-overview">
          <div className="profile-avatar">{initials}</div>
          <div className="profile-overview__copy">
            <span className="eyebrow">Customer profile</span>
            <h1>{resolvedUser.full_name}</h1>
            <p>{resolvedUser.email}</p>
            <div className="profile-overview__chips">
              <span className="micro-chip">Customer</span>
              <span className="micro-chip">{resolvedUser.is_verified ? 'Verified' : 'Not verified'}</span>
              {stats ? (
                <span className="micro-chip">
                  {stats.total_orders} order{stats.total_orders === 1 ? '' : 's'} • {stats.delivered_orders} delivered
                </span>
              ) : null}
            </div>
          </div>
        </div>
        <div className="profile-overview__aside">
          <button className="secondary-button" onClick={() => onNavigate('/profile/details')} type="button">
            Edit profile
          </button>
          <button
            className="text-link"
            disabled={loading || refreshing}
            onClick={() => {
              void loadProfile({ silent: true });
            }}
            type="button"
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <button
            className="text-link text-link--danger"
            onClick={() => {
              logout();
              onToast('Signed out', 'See you again soon.', 'info');
              onNavigate('/');
            }}
            type="button"
          >
            Logout
          </button>
        </div>
      </section>

      <section className="profile-grid">
        <div className="section-card">
          <div className="section-card__header">
            <div>
              <span className="eyebrow">Overview</span>
              <h2>Your account at a glance</h2>
            </div>
          </div>
          <div className="profile-list">
            <div className="profile-list__row"><span>Name</span><strong>{resolvedUser.full_name}</strong></div>
            <div className="profile-list__row"><span>Email</span><strong>{resolvedUser.email}</strong></div>
            <div className="profile-list__row"><span>Phone</span><strong>{resolvedUser.phone_number ?? 'Not added yet'}</strong></div>
            <div className="profile-list__row"><span>Default address</span><strong>{resolvedUser.default_address ?? 'No address saved'}</strong></div>
            <div className="profile-list__row"><span>Total orders</span><strong>{stats?.total_orders ?? '—'}</strong></div>
            <div className="profile-list__row"><span>Delivered</span><strong>{stats?.delivered_orders ?? '—'}</strong></div>
            <div className="profile-list__row"><span>Saved places</span><strong>{stats?.saved_places ?? '—'}</strong></div>
            <div className="profile-list__row"><span>Favorites</span><strong>{stats?.favorites_count ?? '—'}</strong></div>
          </div>
          {errorMessage ? (
            <div className="empty-inline">
              <strong>Profile sync delayed</strong>
              <span>{errorMessage}</span>
            </div>
          ) : null}
        </div>

        <div className="section-card">
          <div className="section-card__header">
            <div>
              <span className="eyebrow">Profile sections</span>
              <h2>Everything customer-related lives here</h2>
            </div>
          </div>
          <div className="profile-actions">
            <button className="profile-action-card" onClick={() => onNavigate('/profile/details')} type="button">
              <strong>User details</strong>
              <span>View and update your name, phone number, and delivery address.</span>
            </button>
            <button className="profile-action-card" onClick={() => onNavigate('/profile/orders')} type="button">
              <strong>Order history</strong>
              <span>Track statuses, totals, and completed meals without leaving profile.</span>
            </button>
            <button className="profile-action-card" onClick={() => onNavigate('/favorites')} type="button">
              <strong>Favorites</strong>
              <span>
                {stats
                  ? `${stats.favorites_count} saved dish${stats.favorites_count === 1 ? '' : 'es'} synced across web and mobile.`
                  : 'See the dishes you have saved for quick access across web and mobile.'}
              </span>
            </button>
            <button className="profile-action-card" onClick={() => onNavigate('/profile/settings')} type="button">
              <strong>Settings</strong>
              <span>Manage notifications, privacy, and recommendation behavior.</span>
            </button>
            <button className="profile-action-card" onClick={() => onNavigate('/profile/preferences')} type="button">
              <strong>User preferences</strong>
              <span>{preferencesSummary}</span>
            </button>
            <button className="profile-action-card" onClick={() => onNavigate('/profile/help')} type="button">
              <strong>Help & support</strong>
              <span>Find quick answers or jump into AI chat when you need guidance.</span>
            </button>
          </div>
        </div>
      </section>

      <section className="section-card">
        <div className="section-card__header">
          <div>
            <span className="eyebrow">Order history</span>
            <h2>Recent orders</h2>
          </div>
          <button className="text-link" onClick={() => onNavigate('/profile/orders')} type="button">
            Open full history
          </button>
        </div>
        {loading ? (
          <div className="orders-list">
            {Array.from({ length: 2 }).map((_, index) => (
              <div className="order-card order-card--skeleton" key={index} />
            ))}
          </div>
        ) : recentOrders.length > 0 ? (
          <div className="orders-list">
            {recentOrders.map((order) => (
              <button
                className="order-card order-card--interactive"
                key={order.id}
                onClick={() => onNavigate(`/orders/${order.id}`)}
                type="button"
              >
                <div className="order-card__header">
                  <div>
                    <strong>{order.restaurant.name}</strong>
                    <span>{formatDateTime(order.placed_at)}</span>
                  </div>
                  <div className="order-card__amount">
                    <strong>{formatCurrency(order.total_amount)}</strong>
                    <span>{order.status.replaceAll('_', ' ')}</span>
                  </div>
                </div>
              </button>
            ))}
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
            <span>Place your first order and this area will turn into your customer timeline.</span>
          </div>
        )}
      </section>
    </div>
  );
}
