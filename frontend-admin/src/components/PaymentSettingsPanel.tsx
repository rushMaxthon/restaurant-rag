import { CircleAlert, CreditCard, KeyRound, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

import { ConfirmDialog } from './ConfirmDialog';
import { StatePanel } from './StatePanel';
import { ApiError, api, formatDate } from '../services/api';
import type {
  PaymentGateway,
  PaymentGatewayAccount,
  RestaurantPaymentSettings,
  UserRole,
} from '../types/app';

/**
 * Whose bank account this restaurant's customers pay into.
 *
 * Every charge on this platform used to land in one account. The money is the
 * restaurant's, so each one holds its own gateway credentials — and this is
 * where they go in.
 *
 * **The secret can never be read back.** The form shows the last four of what
 * is stored and submits an empty secret whenever nobody retypes one, which the
 * server reads as "leave it alone". That is not a limitation to work around:
 * a screen that can display a live API key is a screen that leaks one to
 * anyone who gets a look at it.
 *
 * The lower half is the part an operator actually needs at a glance: which
 * buttons a customer would see right now, and whose account each one settles
 * into. "Settled by the platform" is a temporary arrangement somebody should
 * notice they are still in, rather than discover at a reconciliation.
 */
interface PaymentSettingsPanelProps {
  token: string;
  restaurantId: string;
  role: UserRole;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

interface GatewayForm {
  public_key: string;
  secret_key: string;
  webhook_secret: string;
  is_enabled: boolean;
}

const BLANK: GatewayForm = {
  public_key: '',
  secret_key: '',
  webhook_secret: '',
  is_enabled: false,
};

/** What each gateway's fields are called where the keys are issued. */
const FIELD_LABELS: Record<PaymentGateway, { publicKey: string; secret: string; hint: string }> = {
  RAZORPAY: {
    publicKey: 'Key ID',
    secret: 'Key secret',
    hint: 'From the Razorpay dashboard, under Account & Settings → API Keys.',
  },
  STRIPE: {
    publicKey: 'Publishable key',
    secret: 'Secret key',
    hint: 'From the Stripe dashboard, under Developers → API keys.',
  },
};

export function PaymentSettingsPanel({
  token,
  restaurantId,
  role,
  onToast,
}: PaymentSettingsPanelProps) {
  const [settings, setSettings] = useState<RestaurantPaymentSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<PaymentGateway | null>(null);
  const [form, setForm] = useState<GatewayForm>(BLANK);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState<PaymentGateway | null>(null);
  const isAdmin = role === 'ADMIN';

  useEffect(() => {
    let cancelled = false;
    void api
      .getRestaurantPaymentSettings(token, restaurantId)
      .then((loaded) => {
        if (!cancelled) {
          setSettings(loaded);
          setError(null);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : 'Could not load payment settings');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [restaurantId, token]);

  function startEditing(account: PaymentGatewayAccount): void {
    setEditing(account.gateway);
    // The secret fields start empty every time, including when one is stored.
    // There is nothing to prefill them with, and an input showing dots that
    // are not the real value is worse than one that is plainly blank.
    setForm({
      public_key: account.public_key,
      secret_key: '',
      webhook_secret: '',
      is_enabled: account.is_enabled,
    });
  }

  async function save(gateway: PaymentGateway): Promise<void> {
    setSaving(true);
    try {
      const updated = await api.saveRestaurantPaymentGateway(token, restaurantId, gateway, {
        public_key: form.public_key.trim(),
        // Empty means unchanged, never "clear it".
        secret_key: form.secret_key.trim() || null,
        webhook_secret: form.webhook_secret.trim() || null,
        is_enabled: form.is_enabled,
      });
      setSettings(updated);
      setEditing(null);
      onToast('Payment settings saved', 'Customers see the change on their next checkout.', 'success');
    } catch (caught: unknown) {
      onToast(
        'Could not save this gateway',
        caught instanceof ApiError ? caught.message : 'Something went wrong',
        'error',
      );
    } finally {
      setSaving(false);
    }
  }

  async function remove(gateway: PaymentGateway): Promise<void> {
    setSaving(true);
    try {
      setSettings(await api.deleteRestaurantPaymentGateway(token, restaurantId, gateway));
      setRemoving(null);
      onToast('Gateway removed', 'Its keys are gone and will have to be entered again.', 'success');
    } catch (caught: unknown) {
      onToast(
        'Could not remove this gateway',
        caught instanceof ApiError ? caught.message : 'Something went wrong',
        'error',
      );
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="capability-list">
        <span className="skeleton capability-skeleton" />
        <span className="skeleton capability-skeleton" />
      </div>
    );
  }

  if (error || !settings) {
    return (
      <StatePanel
        description={error ?? 'Could not load payment settings'}
        icon={CreditCard}
        title="Payment settings didn't load"
        tone="error"
      />
    );
  }

  return (
    <div className="page-stack">
      {settings.platform_fallback_in_use ? (
        <p className="mixed-currency" role="note">
          <CircleAlert size={15} strokeWidth={2.2} />
          <span>
            <strong>This restaurant's card payments land in the platform account.</strong> Add
            their own gateway below and the money goes to them instead. Existing orders keep
            whatever settled them.
          </span>
        </p>
      ) : null}

      <div className="capability-list">
        {settings.gateways.map((account) => {
          const labels = FIELD_LABELS[account.gateway];
          const isOpen = editing === account.gateway;

          return (
            <article
              className={
                account.is_enabled ? 'capability' : 'capability capability--off'
              }
              key={account.gateway}
            >
              <div className="capability__copy">
                <div className="capability__title">
                  <strong>{account.label}</strong>
                  <span
                    className={`status-pill status-pill--${
                      account.is_enabled ? 'success' : account.is_configured ? 'warning' : 'muted'
                    }`}
                  >
                    {account.is_enabled ? 'Live' : account.is_configured ? 'Paused' : 'Not set up'}
                  </span>
                </div>

                {account.is_configured ? (
                  <>
                    <p className="gateway__keys">
                      <KeyRound size={13} strokeWidth={2.2} />
                      <code>{account.public_key}</code>
                      <span>
                        secret ending {account.secret_last4 ?? '••••'}
                        {account.has_webhook_secret ? ' · webhook set' : ' · no webhook yet'}
                      </span>
                    </p>
                    {account.updated_by && account.updated_at ? (
                      <p className="capability__why">
                        <span className="capability__actor">
                          {account.updated_by} · {formatDate(account.updated_at)}
                        </span>
                      </p>
                    ) : null}
                  </>
                ) : (
                  <p>{labels.hint}</p>
                )}

                {isOpen ? (
                  <div className="form-grid gateway__form">
                    <label className="field">
                      <span>{labels.publicKey}</span>
                      <input
                        onChange={(event) =>
                          setForm((current) => ({ ...current, public_key: event.target.value }))
                        }
                        placeholder={account.gateway === 'RAZORPAY' ? 'rzp_live_…' : 'pk_live_…'}
                        value={form.public_key}
                      />
                      <small>Safe to share — it appears in the page source of every checkout.</small>
                    </label>

                    <label className="field">
                      <span>{labels.secret}</span>
                      <input
                        autoComplete="off"
                        onChange={(event) =>
                          setForm((current) => ({ ...current, secret_key: event.target.value }))
                        }
                        placeholder={
                          account.is_configured
                            ? `Leave blank to keep the key ending ${account.secret_last4 ?? '••••'}`
                            : 'Required'
                        }
                        type="password"
                        value={form.secret_key}
                      />
                      <small>
                        Encrypted before it is stored and never shown again — not here, not
                        anywhere. Blank leaves the stored key alone.
                      </small>
                    </label>

                    <label className="field form-grid__wide">
                      <span>Webhook secret</span>
                      <input
                        autoComplete="off"
                        onChange={(event) =>
                          setForm((current) => ({ ...current, webhook_secret: event.target.value }))
                        }
                        placeholder={
                          account.has_webhook_secret ? 'Leave blank to keep the stored one' : 'Optional for now'
                        }
                        type="password"
                        value={form.webhook_secret}
                      />
                      <small>
                        Used to verify that a payment update really came from{' '}
                        {account.label}. Payments work without it; confirmations arrive late.
                      </small>
                    </label>

                    <label className="field form-grid__wide gateway__toggle">
                      <input
                        checked={form.is_enabled}
                        onChange={(event) =>
                          setForm((current) => ({ ...current, is_enabled: event.target.checked }))
                        }
                        type="checkbox"
                      />
                      <span>Offer this at checkout</span>
                    </label>

                    <div className="form-grid__wide modal-actions">
                      <button
                        className="secondary-button"
                        disabled={saving}
                        onClick={() => setEditing(null)}
                        type="button"
                      >
                        Cancel
                      </button>
                      <button
                        className="primary-button"
                        disabled={saving || !form.public_key.trim()}
                        onClick={() => void save(account.gateway)}
                        type="button"
                      >
                        {saving ? 'Saving…' : 'Save gateway'}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>

              {isAdmin && !isOpen ? (
                <div className="capability__actions">
                  <button
                    className={account.is_configured ? 'secondary-button' : 'primary-button'}
                    onClick={() => startEditing(account)}
                    type="button"
                  >
                    {account.is_configured ? 'Edit keys' : 'Add account'}
                  </button>
                  {account.is_configured ? (
                    <button
                      className="capability__reset"
                      onClick={() => setRemoving(account.gateway)}
                      type="button"
                    >
                      <Trash2 size={13} strokeWidth={2.2} />
                      Remove
                    </button>
                  ) : null}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>

      <div className="admin-surface__header">
        <div>
          <span className="eyebrow">At checkout</span>
          <h2>What a customer sees</h2>
          <p className="hint-text">
            A button appears only when the branch has the method switched on and a gateway is
            configured that can settle it.
          </p>
        </div>
      </div>

      <div className="method-list">
        {settings.methods.map((method) => (
          <div
            className={method.is_available ? 'method-row' : 'method-row method-row--off'}
            key={method.method}
          >
            <span className="method-row__dot" />
            <div>
              <strong>{method.label}</strong>
              <span>
                {method.is_available
                  ? `Settled by ${method.settled_by}`
                  : method.blocked_reason}
              </span>
            </div>
          </div>
        ))}
      </div>

      <ConfirmDialog
        busy={saving}
        cancelLabel="Keep it"
        confirmLabel="Remove the keys"
        description="Their stored keys are deleted. Nothing that has already been paid changes, but this gateway stops working until somebody enters the keys again."
        eyebrow="Remove gateway"
        onCancel={() => setRemoving(null)}
        onConfirm={() => removing && void remove(removing)}
        open={removing !== null}
        title={`Remove ${removing ? FIELD_LABELS[removing].publicKey.split(' ')[0] : ''} credentials?`}
        tone="danger"
      />
    </div>
  );
}
