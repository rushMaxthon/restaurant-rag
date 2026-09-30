import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Check,
  ChevronLeft,
  CircleAlert,
  Link2,
  Pause,
  Play,
  Plug,
  Trash2,
} from 'lucide-react';
import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  RestaurantScopePicker,
  RestaurantScopePrompt,
} from '../components/marketing/RestaurantScopePicker';
import { useMarketingScope } from '../hooks/useMarketingScope';
import { channelsInFamily, getChannel, type ChannelFamily } from '../components/marketing/channels';
import { formatDate } from '../services/api';
import {
  connectChannel,
  disconnectChannel,
  listChannels,
  setChannelEnabled,
} from '../services/marketing/marketingApi';
import type {
  ChannelConnection,
  ConnectionField,
  MarketingChannel,
} from '../services/marketing/types';

interface ChannelsPageProps {
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: 'success' | 'error' | 'info',
  ) => void;
}

const FAMILY_COPY: Record<ChannelFamily, { title: string; sub: string }> = {
  DIRECT: {
    title: 'Send straight to your customers',
    sub: 'You choose who gets it. Only people who agreed to hear from you.',
  },
  SOCIAL: {
    title: 'Post for your followers',
    sub: 'Anyone can see it. You cannot choose who — you can pay to reach more.',
  },
};

/**
 * "What can I actually send on?" — the screen the campaign builder points at.
 *
 * Every channel but push needs something from the owner before it can deliver
 * a single message, and until this page existed there was nowhere to give it.
 * The builder's Connect panel could only describe what was needed; this is
 * where it gets done.
 *
 * Two decisions shape the form:
 *
 * **A saved secret is never shown, and never has to be retyped.** The field
 * renders empty with a "kept as it is" note, and the backend merges rather
 * than replaces. An owner correcting their sender name would otherwise blank
 * their API key by leaving its box empty, and would not find out until the
 * next send failed.
 *
 * **Pausing is not disconnecting.** An owner switching WhatsApp off for a
 * month should not have to re-authorise Meta afterwards, so the two are
 * different buttons with different consequences, and only one of them asks
 * for confirmation.
 */
export function ChannelsPage({ onNavigate, onToast }: ChannelsPageProps) {
  // Every `/marketing/*` call requires `restaurant_id` from an ADMIN and
  // refuses it from an OWNER. Without this an admin arriving here by deep
  // link or refresh — the remembered scope lives in localStorage and is only
  // written by having visited the Hub first — got
  // `400 restaurant_id is required` and a page that looked broken.
  const scope = useMarketingScope();
  const [rows, setRows] = useState<ChannelConnection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<MarketingChannel | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = useState<MarketingChannel | null>(null);

  /** Re-read after every change, so the row shows what the server now holds. */
  const load = useCallback(async () => {
    try {
      const next = await listChannels();
      setRows(next);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Your channels did not load.');
      setRows(null);
    }
  }, []);

  // The mount fetch is written as a subscription rather than as `void load()`
  // — state is set in the promise callback and dropped if this unmounts
  // first. The sibling marketing pages call their loader synchronously and
  // trip `react-hooks/set-state-in-effect` for it; there is no reason for a
  // new page to inherit that.
  useEffect(() => {
    if (!scope.ready) {
      return;
    }
    let cancelled = false;
    // Keyed on the chosen restaurant: switching it has to re-read, or the
    // page would show one tenant's connections under another's name.
    void listChannels()
      .then((next) => {
        if (!cancelled) {
          setRows(next);
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : 'Your channels did not load.');
        }
      });
    return () => {
      cancelled = true;
    };
  }, [scope.ready, scope.selectedRestaurantId]);

  const byChannel = useMemo(() => {
    const map = new Map<MarketingChannel, ChannelConnection>();
    for (const row of rows ?? []) {
      map.set(row.channel, row);
    }
    return map;
  }, [rows]);

  const openForm = (channel: MarketingChannel) => {
    setEditing(channel);
    // Pre-filled with what is saved, except the secrets — which cannot be
    // shown and must not be blanked by being left empty.
    const row = byChannel.get(channel);
    const prefill: Record<string, string> = {};
    for (const field of row?.requirements ?? []) {
      if (!field.secret) {
        const current = row?.config?.[field.key];
        prefill[field.key] = current === null || current === undefined ? '' : String(current);
      }
    }
    setValues(prefill);
  };

  const handleSave = async (channel: MarketingChannel) => {
    setBusy(true);
    try {
      await connectChannel(channel, values);
      await load();
      setEditing(null);
      onToast(
        `${getChannel(channel).label} connected`,
        'Send yourself a test from any campaign to check it works.',
        'success',
      );
    } catch (caught) {
      onToast(
        'Not connected',
        caught instanceof Error ? caught.message : 'That could not be saved.',
        'error',
      );
    } finally {
      setBusy(false);
    }
  };

  const handleToggle = async (channel: MarketingChannel, enabled: boolean) => {
    setBusy(true);
    try {
      await setChannelEnabled(channel, enabled);
      await load();
      onToast(
        enabled ? 'Switched back on' : 'Paused',
        enabled
          ? `${getChannel(channel).label} campaigns can go out again.`
          : `${getChannel(channel).label} keeps its setup — nothing will send until you switch it back on.`,
        'success',
      );
    } catch (caught) {
      onToast(
        'That did not work',
        caught instanceof Error ? caught.message : 'Try again in a moment.',
        'error',
      );
    } finally {
      setBusy(false);
    }
  };

  const handleDisconnect = async (channel: MarketingChannel) => {
    setConfirmDisconnect(null);
    setBusy(true);
    try {
      await disconnectChannel(channel);
      await load();
      onToast(
        `${getChannel(channel).label} disconnected`,
        'We have forgotten its settings. You can connect it again any time.',
        'success',
      );
    } catch (caught) {
      onToast(
        'That did not work',
        caught instanceof Error ? caught.message : 'Try again in a moment.',
        'error',
      );
    } finally {
      setBusy(false);
    }
  };

  if (!scope.ready) {
    return <RestaurantScopePrompt scope={scope} what="Connected channels" />;
  }

  if (error) {
    return (
      <div className="mkt">
        <div className="mkt-empty">
          <span className="mkt-empty__icon">
            <CircleAlert size={26} strokeWidth={2} />
          </span>
          <strong>Your channels didn't load</strong>
          <p>{error}</p>
          <button className="mkt-btn mkt-btn--ghost" onClick={() => void load()} type="button">
            Try again
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mkt">
      <header className="mkt-card__head">
        <button className="mkt-back" onClick={() => onNavigate('/marketing')} type="button">
          <ChevronLeft size={14} strokeWidth={2.5} />
          Marketing
        </button>
        <h1 className="mkt-h1">Where you can send from</h1>
        <p className="mkt-sub">
          Push notifications work out of the box. Everything else needs to be linked to the
          account you already have with them — once, and then it stays.
        </p>
        <RestaurantScopePicker scope={scope} />
      </header>

      {rows === null ? (
        <div className="mkt-card">
          <span className="mkt-skeleton mkt-skeleton--title" />
          <span className="mkt-skeleton mkt-skeleton--block" />
        </div>
      ) : (
        (['DIRECT', 'SOCIAL'] as ChannelFamily[]).map((family) => (
          <section className="mkt-card" key={family}>
            <div className="mkt-card__head">
              <span className="mkt-eyebrow">{FAMILY_COPY[family].title}</span>
              <p className="mkt-sub">{FAMILY_COPY[family].sub}</p>
            </div>

            <div className="mkt-section">
              {channelsInFamily(family).map((definition) => {
                const row = byChannel.get(definition.key);
                const Icon = definition.icon;
                const isPush = definition.key === 'PUSH';
                const isEditing = editing === definition.key;

                return (
                  <article className="mkt-conn" key={definition.key}>
                    <div className="mkt-conn__row">
                      <span aria-hidden="true" className="mkt-pick__icon">
                        <Icon size={18} strokeWidth={2.1} />
                      </span>

                      <div className="mkt-conn__copy">
                        <strong>{definition.label}</strong>
                        <span>
                          {row?.connected
                            ? row.identity
                              ? `Sending as ${row.identity}`
                              : 'Connected'
                            : row?.status === 'DISABLED'
                              ? 'Paused — its setup is kept'
                              : definition.tagline}
                        </span>
                        {/* Connected and verified are different facts. A
                            token that worked in March is not a token that
                            works today, and the owner should be told which
                            one they have rather than left to assume. */}
                        {row?.connected && !isPush ? (
                          <span className="mkt-conn__meta">
                            {row.verified_at
                              ? `Last proven to work ${formatDate(row.verified_at)}`
                              : 'Not tested yet — send yourself a test from a campaign'}
                          </span>
                        ) : null}
                        {row?.last_error ? (
                          <span className="mkt-conn__meta mkt-conn__meta--bad">
                            {row.last_error}
                          </span>
                        ) : null}
                      </div>

                      {row?.connected ? (
                        <span className="mkt-status mkt-status--sent">
                          <Check size={11} strokeWidth={3} />
                          Ready
                        </span>
                      ) : row?.status === 'DISABLED' ? (
                        <span className="mkt-status mkt-status--cancelled">Paused</span>
                      ) : (
                        <span className="mkt-status mkt-status--draft">Not connected</span>
                      )}

                      <div className="mkt-conn__actions">
                        {isPush ? (
                          <span className="mkt-field__hint">
                            Part of your app — nothing to set up.
                          </span>
                        ) : (
                          <>
                            <button
                              className="mkt-btn mkt-btn--ghost mkt-btn--sm"
                              disabled={busy}
                              onClick={() => (isEditing ? setEditing(null) : openForm(definition.key))}
                              type="button"
                            >
                              <Plug size={14} strokeWidth={2.3} />
                              {row?.status ? 'Edit' : 'Connect'}
                            </button>
                            {row?.status ? (
                              <>
                                <button
                                  className="mkt-btn mkt-btn--quiet mkt-btn--sm"
                                  disabled={busy}
                                  onClick={() =>
                                    void handleToggle(definition.key, !row.connected)
                                  }
                                  type="button"
                                >
                                  {row.connected ? (
                                    <>
                                      <Pause size={14} strokeWidth={2.3} />
                                      Pause
                                    </>
                                  ) : (
                                    <>
                                      <Play size={14} strokeWidth={2.3} />
                                      Switch on
                                    </>
                                  )}
                                </button>
                                <button
                                  aria-label={`Disconnect ${definition.label}`}
                                  className="mkt-icon-btn mkt-icon-btn--danger"
                                  disabled={busy}
                                  onClick={() => setConfirmDisconnect(definition.key)}
                                  type="button"
                                >
                                  <Trash2 size={15} strokeWidth={2.2} />
                                </button>
                              </>
                            ) : null}
                          </>
                        )}
                      </div>
                    </div>

                    {isEditing ? (
                      <div className="mkt-conn__form">
                        {definition.setup.length > 0 ? (
                          <ul className="mkt-conn__steps">
                            {definition.setup.map((line) => (
                              <li key={line}>{line}</li>
                            ))}
                          </ul>
                        ) : null}

                        {(row?.requirements ?? []).map((field: ConnectionField) => (
                          <label className="mkt-field" key={field.key}>
                            <span className="mkt-field__label">
                              {field.label}
                              {field.required ? null : <span className="mkt-field__count">Optional</span>}
                            </span>
                            <input
                              onChange={(event) =>
                                setValues((current) => ({
                                  ...current,
                                  [field.key]: event.target.value,
                                }))
                              }
                              placeholder={field.example}
                              type={field.secret ? 'password' : 'text'}
                              value={values[field.key] ?? ''}
                            />
                            <span className="mkt-field__hint">
                              {field.secret && row?.status
                                ? 'Leave blank to keep the one you already saved.'
                                : field.help}
                            </span>
                          </label>
                        ))}

                        <div className="mkt-conn__save">
                          <button
                            className="mkt-btn mkt-btn--primary mkt-btn--sm"
                            disabled={busy}
                            onClick={() => void handleSave(definition.key)}
                            type="button"
                          >
                            <Link2 size={15} strokeWidth={2.3} />
                            {busy ? 'Saving…' : 'Save'}
                          </button>
                          <button
                            className="mkt-btn mkt-btn--quiet mkt-btn--sm"
                            disabled={busy}
                            onClick={() => setEditing(null)}
                            type="button"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </section>
        ))
      )}

      <ConfirmDialog
        confirmLabel="Disconnect it"
        description={
          confirmDisconnect
            ? `We will forget how to reach ${getChannel(confirmDisconnect).label}, including the access token. Campaigns already saved for it stay as drafts. If you only want to stop sending for a while, use Pause instead — that keeps the setup.`
            : ''
        }
        eyebrow="Disconnect"
        onCancel={() => setConfirmDisconnect(null)}
        onConfirm={() => confirmDisconnect && void handleDisconnect(confirmDisconnect)}
        open={confirmDisconnect !== null}
        title={
          confirmDisconnect
            ? `Disconnect ${getChannel(confirmDisconnect).label}?`
            : 'Disconnect?'
        }
        tone="danger"
      />
    </div>
  );
}
