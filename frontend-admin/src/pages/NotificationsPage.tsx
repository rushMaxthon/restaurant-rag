import { Bell, Send, Users, UserRound, Store, Shield } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { PageIntro } from '../components/PageIntro';
import { humanizeEnum, pluralize } from '../services/format';
import { useAdminStore } from '../hooks/useAdminStore';
import { api, ApiError } from '../services/api';
import { buildAdminUsersCacheKey } from './AdminUsersPage';
import {
  getPageSnapshot,
  hasPageSnapshot,
  setPageSnapshot,
  tokenScope,
} from '../services/pageCache';
import type {
  NotificationAudience,
  NotificationType,
  NotificationHistoryItem,
  SendNotificationResponse,
  User,
} from '../types/app';

interface NotificationsPageProps {
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

const AUDIENCE_OPTIONS: Array<{
  value: NotificationAudience;
  label: string;
  description: string;
}> = [
  {
    value: 'ALL_USERS',
    label: 'All users',
    description: 'Broadcast to every active user with a registered device token.',
  },
  {
    value: 'CUSTOMERS',
    label: 'Customers',
    description: 'Reach customers using the mobile app for order and account updates.',
  },
  {
    value: 'OWNERS',
    label: 'Restaurant owners',
    description: 'Send owner-facing operational or onboarding updates.',
  },
  {
    value: 'ADMINS',
    label: 'Admins',
    description: 'Internal administrative notifications only.',
  },
  {
    value: 'SPECIFIC_USER',
    label: 'Specific user',
    description: 'Target one user directly by selecting them from the active user list.',
  },
];

const CATEGORY_OPTIONS = [
  { value: '', label: 'General update' },
  { value: 'PROMOTION', label: 'Promotion' },
  { value: 'OPERATIONS', label: 'Operations' },
  { value: 'ORDER_UPDATE', label: 'Order update' },
  { value: 'ANNOUNCEMENT', label: 'Announcement' },
];

const NOTIFICATION_TYPE_OPTIONS: Array<{
  value: NotificationType;
  label: string;
  description: string;
}> = [
  {
    value: 'GENERAL',
    label: 'General notification',
    description: 'Standard informational push notification.',
  },
];

function audienceLabel(value: NotificationAudience) {
  return AUDIENCE_OPTIONS.find(option => option.value === value)?.label ?? value;
}

function categoryLabel(value: string | null) {
  return CATEGORY_OPTIONS.find(option => option.value === (value ?? ''))?.label ?? value ?? 'General update';
}

function formatTimestamp(value: string) {
  return new Date(value).toLocaleString();
}

export function NotificationsPage({ onToast }: NotificationsPageProps) {
  const { token } = useAdminStore();
  const scope = tokenScope(token);
  // Shares AdminUsersPage's exact cache key - one fetch serves both.
  const usersKey = buildAdminUsersCacheKey(scope);
  const historyKey = `notification-history:${scope}`;
  const [audience, setAudience] = useState<NotificationAudience>('CUSTOMERS');
  const [notificationType, setNotificationType] =
    useState<NotificationType>('GENERAL');
  const [title, setTitle] = useState('');
  const [message, setMessage] = useState('');
  const [category, setCategory] = useState('');
  const [targetUserId, setTargetUserId] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // Only true when neither list has been fetched yet this session - not on
  // every mount, so revisiting this page keeps showing its data instead of a
  // skeleton.
  const [loading, setLoading] = useState(
    () => !hasPageSnapshot(usersKey) || !hasPageSnapshot(historyKey),
  );
  const [users, setUsers] = useState<User[]>(() => getPageSnapshot<User[]>(usersKey) ?? []);
  const [history, setHistory] = useState<NotificationHistoryItem[]>(
    () => getPageSnapshot<NotificationHistoryItem[]>(historyKey) ?? [],
  );
  const [lastResult, setLastResult] = useState<SendNotificationResponse | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  // `force`: bypasses the cache. Used by the error-recovery reload below and
  // never by the mount effect, which is what makes revisiting this page free.
  const loadData = useCallback(
    async (force = false) => {
      if (!token) {
        return;
      }

      if (!force) {
        const cachedUsers = getPageSnapshot<User[]>(usersKey);
        const cachedHistory = getPageSnapshot<NotificationHistoryItem[]>(historyKey);
        if (cachedUsers && cachedHistory) {
          setUsers(cachedUsers);
          setHistory(cachedHistory);
          setLoading(false);
          return;
        }
      }

      setLoading(true);
      try {
        const [historyResponse, usersResponse] = await Promise.all([
          api.getNotificationHistory(token),
          api.getAdminUsers(token),
        ]);
        setHistory(historyResponse);
        setUsers(usersResponse);
        setPageSnapshot(historyKey, historyResponse);
        setPageSnapshot(usersKey, usersResponse);
      } catch (error) {
        const messageText =
          error instanceof Error ? error.message : 'Unable to load notification data.';
        onToast('Notifications unavailable', messageText, 'error');
      } finally {
        setLoading(false);
      }
    },
    [historyKey, onToast, token, usersKey],
  );

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const estimatedRecipients = useMemo(() => {
    switch (audience) {
      case 'ALL_USERS':
        return users.filter(user => user.is_active).length;
      case 'CUSTOMERS':
        return users.filter(user => user.is_active && user.role === 'CUSTOMER').length;
      case 'OWNERS':
        return users.filter(user => user.is_active && user.role === 'OWNER').length;
      case 'ADMINS':
        return users.filter(user => user.is_active && user.role === 'ADMIN').length;
      case 'SPECIFIC_USER':
        return targetUserId ? 1 : 0;
      default:
        return 0;
    }
  }, [audience, targetUserId, users]);

  const targetUser = useMemo(
    () => users.find(user => user.id === targetUserId) ?? null,
    [targetUserId, users],
  );

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!token) {
      onToast('Session expired', 'Please login again to send notifications.', 'error');
      return;
    }
    if (audience === 'SPECIFIC_USER' && !targetUserId) {
      onToast('Choose a user', 'Select the target user before sending this notification.', 'info');
      return;
    }
    setConfirmOpen(true);
  };

  const performSend = async () => {
    setConfirmOpen(false);
    if (!token) {
      return;
    }
    setSubmitting(true);
    try {
      const response = await api.sendNotification(token, {
        audience,
        notification_type: notificationType,
        title: title.trim(),
        message: message.trim(),
        category: category || null,
        target_user_id: audience === 'SPECIFIC_USER' ? targetUserId : null,
      });
      setLastResult(response);
      setHistory(current => {
        const next = [response.history, ...current].slice(0, 20);
        setPageSnapshot(historyKey, next);
        return next;
      });
      onToast(
        'Notification sent',
        `Delivered to ${response.success_count} devices with ${response.failure_count} failures.`,
        response.failure_count > 0 ? 'info' : 'success',
      );
      setTitle('');
      setMessage('');
      setCategory('');
      setTargetUserId('');
      setNotificationType('GENERAL');
    } catch (error) {
      const messageText =
        error instanceof ApiError || error instanceof Error
          ? error.message
          : 'Unable to send the notification.';
      onToast('Send failed', messageText, 'error');
      await loadData(true);
    } finally {
      setSubmitting(false);
    }
  };

  const selectedAudience = AUDIENCE_OPTIONS.find(option => option.value === audience);
  const selectedNotificationType = NOTIFICATION_TYPE_OPTIONS.find(
    option => option.value === notificationType,
  );

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Messaging"
        title="Notification Center"
        description="Broadcast customer, owner, and operational updates from one Firebase-backed workspace."
      />

      <section className="ntf-layout">
        <section className="admin-surface ntf-card ntf-compose">
          <header className="ntf-card__header">
            <span className="ntf-card__icon">
              <Bell size={16} strokeWidth={2.1} />
            </span>
            <div>
              <h2>Compose push notification</h2>
              <p>Pick the audience, write the message, review reach, send.</p>
            </div>
          </header>

          <form className="ntf-form" onSubmit={submit}>
            <div className="ntf-form__row">
              <label className="field">
                <span>Notification type</span>
                <select
                  onChange={event =>
                    setNotificationType(event.target.value as NotificationType)
                  }
                  value={notificationType}
                >
                  {NOTIFICATION_TYPE_OPTIONS.map(option => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Audience</span>
                <select
                  onChange={event => {
                    const nextAudience = event.target.value as NotificationAudience;
                    setAudience(nextAudience);
                    if (nextAudience !== 'SPECIFIC_USER') {
                      setTargetUserId('');
                    }
                  }}
                  value={audience}
                >
                  {AUDIENCE_OPTIONS.map(option => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="field">
                <span>Category</span>
                <select onChange={event => setCategory(event.target.value)} value={category}>
                  {CATEGORY_OPTIONS.map(option => (
                    <option key={option.label} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="ntf-scope">
              <span className="ntf-scope__icon">
                {audience === 'CUSTOMERS' ? <UserRound size={14} strokeWidth={2.1} /> : null}
                {audience === 'OWNERS' ? <Store size={14} strokeWidth={2.1} /> : null}
                {audience === 'ADMINS' ? <Shield size={14} strokeWidth={2.1} /> : null}
                {audience === 'ALL_USERS' || audience === 'SPECIFIC_USER' ? (
                  <Users size={14} strokeWidth={2.1} />
                ) : null}
              </span>
              <div className="ntf-scope__copy">
                <strong>{audienceLabel(audience)}</strong>
                <span>
                  {targetUser
                    ? `${targetUser.full_name} (${targetUser.email})`
                    : selectedAudience?.description}
                </span>
              </div>
              <span className="ntf-scope__count">
                {estimatedRecipients}{' '}
                {estimatedRecipients === 1 ? 'recipient' : 'recipients'}
              </span>
            </div>

            {audience === 'SPECIFIC_USER' ? (
              <label className="field">
                <span>Target user</span>
                <select onChange={event => setTargetUserId(event.target.value)} value={targetUserId}>
                  <option value="">Select a user</option>
                  {users
                    .filter(user => user.is_active)
                    .map(user => (
                      <option key={user.id} value={user.id}>
                        {user.full_name} · {user.email} · {user.role}
                      </option>
                    ))}
                </select>
                <small>
                  {targetUser
                    ? `Selected: ${targetUser.full_name} (${targetUser.email})`
                    : 'Only active users are shown here.'}
                </small>
              </label>
            ) : null}

            <label className="field">
              <span>Title</span>
              <input
                maxLength={160}
                onChange={event => setTitle(event.target.value)}
                placeholder="Example: Weekend offer is live"
                required
                value={title}
              />
            </label>

            <label className="field">
              <span>Message</span>
              <textarea
                maxLength={2000}
                onChange={event => setMessage(event.target.value)}
                placeholder="Write the push message customers will see on their device."
                required
                rows={5}
                value={message}
              />
            </label>

            <div className="ntf-sendbar">
              <div className="ntf-sendbar__meta">
                <span>
                  <Users size={13} strokeWidth={2.2} /> {estimatedRecipients}{' '}
                  {estimatedRecipients === 1 ? 'recipient' : 'recipients'}
                </span>
                <span>{selectedNotificationType?.label}</span>
                <span>Instant delivery</span>
              </div>
              <button className="primary-button" disabled={submitting} type="submit">
                <Send size={15} strokeWidth={2.1} />
                {submitting ? 'Sending…' : 'Send notification'}
              </button>
            </div>
          </form>
        </section>

        <div className="ntf-rail">
          <section className="admin-surface ntf-card">
            <header className="ntf-card__header">
              <span className="ntf-card__icon">
                <Users size={16} strokeWidth={2.1} />
              </span>
              <div>
                <h2>Delivery result</h2>
                <p>Outcome of the most recent send.</p>
              </div>
            </header>

            {lastResult ? (
              <div className="ntf-result-grid">
                <article className="ntf-result">
                  <span>Target users</span>
                  <strong>{lastResult.target_user_count}</strong>
                </article>
                <article className="ntf-result">
                  <span>Attempted devices</span>
                  <strong>{lastResult.sent_count}</strong>
                </article>
                <article className="ntf-result ntf-result--success">
                  <span>Delivered</span>
                  <strong>{lastResult.success_count}</strong>
                </article>
                <article
                  className={
                    lastResult.failure_count > 0
                      ? 'ntf-result ntf-result--danger'
                      : 'ntf-result'
                  }
                >
                  <span>Failures</span>
                  <strong>{lastResult.failure_count}</strong>
                </article>
              </div>
            ) : (
              <div className="ntf-empty">
                <strong>No delivery yet</strong>
                <span>Send a notification to view the delivery result summary here.</span>
              </div>
            )}
          </section>

          <section className="admin-surface ntf-card ntf-history">
            <header className="ntf-card__header">
              <span className="ntf-card__icon">
                <Bell size={16} strokeWidth={2.1} />
              </span>
              <div>
                <h2>Recent sends</h2>
                <p>Last campaigns with delivery counts.</p>
              </div>
            </header>

            {loading ? (
              <div className="ntf-empty">
                <strong>Loading notification history…</strong>
                <span>Recent campaigns and delivery counts will appear here.</span>
              </div>
            ) : history.length === 0 ? (
              <div className="ntf-empty">
                <strong>No notifications yet</strong>
                <span>Your first sent campaign will appear here with delivery counts.</span>
              </div>
            ) : (
              <div className="ntf-history__list">
                {history.map(item => (
                  <article className="ntf-history__item" key={item.id}>
                    <div className="ntf-history__top">
                      <strong>{item.title}</strong>
                      <span
                        className={
                          item.failure_count > 0
                            ? 'ntf-history__badge ntf-history__badge--warning'
                            : 'ntf-history__badge'
                        }
                      >
                        {item.success_count}/{item.sent_count} delivered
                      </span>
                    </div>
                    <span className="ntf-history__meta">
                      {humanizeEnum(item.notification_type)} · {audienceLabel(item.audience)} ·{' '}
                      {categoryLabel(item.category)} · {formatTimestamp(item.created_at)}
                    </span>
                    <p>{item.message}</p>
                    <div className="ntf-history__stats">
                      <span>Users: {item.target_user_count}</span>
                      <span>Failures: {item.failure_count}</span>
                      <span>By: {item.created_by_name ?? 'Unknown admin'}</span>
                    </div>
                    {item.failure_reason ? (
                      <div className="ntf-history__error">{item.failure_reason}</div>
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      </section>

      <ConfirmDialog
        confirmLabel="Send now"
        description={`"${title.trim() || 'This notification'}" will be sent to ${pluralize(estimatedRecipients, 'user')} (${audienceLabel(audience)}) immediately. Push notifications cannot be recalled.`}
        eyebrow="Confirm send"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          void performSend();
        }}
        open={confirmOpen}
        title="Send this push notification?"
      />
    </div>
  );
}
