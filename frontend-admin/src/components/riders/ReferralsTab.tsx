import { Gift, Save, XCircle } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { EmptyPanel } from '../EmptyPanel';
import { Modal } from '../Modal';
import { ResponsiveTable, type TableColumn } from '../ResponsiveTable';
import { StatusPill } from '../StatusPill';
import { useMoney } from '../../hooks/useMoney';
import { ApiError, api } from '../../services/api';
import {
  STATUS_LABEL,
  draftFrom,
  progressLabel,
  referralExample,
  referralSettingsError,
  settingsFrom,
  type ReferralDraft,
} from '../../services/riderReferral';
import type { AdminReferralRow, ReferralStatus, ToastMessage } from '../../types/app';

interface Props {
  token: string;
  onToast: (title: string, description: string, tone?: ToastMessage['tone']) => void;
}

const FILTERS: Array<ReferralStatus | 'ALL'> = ['ALL', 'IN_PROGRESS', 'WAITING', 'EARNED', 'EXPIRED', 'CANCELLED'];

/**
 * Riders -> Referrals: the programme's terms and who referred whom
 * (`services/fleet/referral.py`). New terms apply to codes accepted from
 * now on; a referral keeps the terms it was accepted on. Cancel is for a
 * referral that looks wrong, and is refused once its bonus has been paid.
 */
export function ReferralsTab({ token, onToast }: Props) {
  const money = useMoney();
  const [saved, setSaved] = useState<ReferralDraft | null>(null);
  const [draft, setDraft] = useState<ReferralDraft | null>(null);
  const [rows, setRows] = useState<AdminReferralRow[] | null>(null);
  const [filter, setFilter] = useState<ReferralStatus | 'ALL'>('ALL');
  const [error, setError] = useState<string | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState<AdminReferralRow | null>(null);
  const [reason, setReason] = useState('');

  useEffect(() => {
    api
      .getReferralSettings(token)
      .then((s) => {
        setSaved(draftFrom(s));
        setDraft(draftFrom(s));
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token]);

  const load = useCallback(() => {
    api
      .listReferrals(token, filter === 'ALL' ? undefined : filter)
      .then((list) => {
        setRows(list);
        setListError(null);
      })
      .catch((e: unknown) => setListError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token, filter]);
  useEffect(load, [load]);

  async function save() {
    if (!draft || referralSettingsError(draft)) return;
    setBusy(true);
    try {
      const next = draftFrom(await api.saveReferralSettings(token, settingsFrom(draft)));
      setSaved(next);
      setDraft(next);
      onToast('Referral settings saved', 'They apply to codes accepted from now on.', 'success');
    } catch (e: unknown) {
      onToast('Could not save', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function confirmCancel() {
    if (!cancelling || !reason.trim()) return;
    setBusy(true);
    try {
      await api.cancelReferral(token, cancelling.referred_user_id, reason.trim());
      onToast(
        'Referral cancelled',
        `${cancelling.referred_name} no longer earns ${cancelling.referrer_name} a bonus.`,
        'success',
      );
      setCancelling(null);
      setReason('');
      load();
    } catch (e: unknown) {
      onToast('Could not cancel', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <section className="admin-surface">
        <EmptyPanel description={error} title="Referral settings didn't load" />
      </section>
    );
  }

  const formError = draft ? referralSettingsError(draft) : null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const setText = (key: Exclude<keyof ReferralDraft, 'enabled'>) => (e: React.ChangeEvent<HTMLInputElement>) => {
    if (draft) setDraft({ ...draft, [key]: e.target.value });
  };

  const columns: Array<TableColumn<AdminReferralRow>> = [
    {
      id: 'new',
      header: 'New rider',
      render: (r) => <strong>{r.referred_name}</strong>,
      mobileLabel: 'New rider',
      hideOnMobile: true,
    },
    { id: 'by', header: 'Referred by', render: (r) => `${r.referrer_name} (${r.code})`, mobileLabel: 'Referred by' },
    { id: 'progress', header: 'Progress', render: (r) => progressLabel(r), mobileLabel: 'Progress' },
    {
      id: 'bonus',
      header: 'Bonus',
      render: (r) =>
        `${money.format(Number(r.referrer_amount))} + ${money.format(Number(r.joiner_amount))}${r.paid ? ' · paid' : ''}`,
      mobileLabel: 'Bonus',
    },
    { id: 'status', header: 'Status', render: (r) => <StatusPill status={r.status} />, mobileLabel: 'Status' },
  ];

  return (
    <>
      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Refer &amp; earn</span>
            <h2>Rider referral programme</h2>
            <p className="hint-text">{draft ? referralExample(draft) : 'Loading…'}</p>
          </div>
        </div>
        {draft ? (
          <>
            <div className="form-grid">
              <label className="field">
                <span>Programme on</span>
                <input
                  checked={draft.enabled}
                  onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
                  type="checkbox"
                />
                <small>Off: no new codes are accepted and nothing new is earned. Bonuses already earned still pay.</small>
              </label>
              <label className="field">
                <span>Referrer gets (₹)</span>
                <input inputMode="decimal" min={0} onChange={setText('referrer_amount')} type="number" value={draft.referrer_amount} />
              </label>
              <label className="field">
                <span>New rider gets (₹)</span>
                <input inputMode="decimal" min={0} onChange={setText('joiner_amount')} type="number" value={draft.joiner_amount} />
              </label>
              <label className="field">
                <span>Deliveries needed</span>
                <input min={1} onChange={setText('deliveries_required')} type="number" value={draft.deliveries_required} />
              </label>
              <label className="field">
                <span>Days allowed after approval</span>
                <input min={1} onChange={setText('days_allowed')} type="number" value={draft.days_allowed} />
              </label>
            </div>
            {formError ? <p role="alert">{formError}</p> : null}
            <div className="modal-actions">
              <button
                className="primary-button"
                disabled={!dirty || Boolean(formError) || busy}
                onClick={() => void save()}
                type="button"
              >
                <Save size={15} /> {busy ? 'Saving…' : 'Save'}
              </button>
            </div>
          </>
        ) : null}
      </section>

      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Referrals</span>
            <h2>Who referred whom</h2>
          </div>
          <select aria-label="Status" onChange={(e) => setFilter(e.target.value as ReferralStatus | 'ALL')} value={filter}>
            {FILTERS.map((f) => (
              <option key={f} value={f}>
                {f === 'ALL' ? 'All' : STATUS_LABEL[f]}
              </option>
            ))}
          </select>
        </div>
        <ResponsiveTable
          actions={[
            {
              id: 'cancel',
              label: 'Cancel referral',
              icon: XCircle,
              onClick: (r: AdminReferralRow) => setCancelling(r),
              tone: 'danger' as const,
              hidden: (r: AdminReferralRow) => r.paid || r.status === 'CANCELLED' || r.status === 'EXPIRED',
            },
          ]}
          columns={columns}
          emptyDescription="When a new rider signs up with a code, they show up here."
          emptyTitle="No referrals yet"
          error={listError}
          errorTitle="Referrals didn't load"
          keyExtractor={(r) => r.referred_user_id}
          loading={rows === null && !listError}
          mobileStatus={(r) => <StatusPill status={r.status} />}
          mobileSubtitle={(r) => progressLabel(r)}
          mobileTitle={(r) => r.referred_name}
          onRetry={load}
          rows={rows ?? []}
        />
      </section>

      {cancelling ? (
        <Modal busy={busy} className="modal-card--compact" labelledBy="cancel-ref-title" onClose={() => setCancelling(null)}>
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">
                <Gift size={14} /> Referral
              </span>
              <h2 id="cancel-ref-title">Cancel {cancelling.referred_name}&rsquo;s referral?</h2>
              <p className="hint-text">Nobody is paid for it, and it cannot be undone.</p>
            </div>
            <button aria-label="Close" className="modal-close" onClick={() => setCancelling(null)} type="button">
              ×
            </button>
          </div>
          <div className="form-grid modal-card__body">
            <label className="field form-grid__wide">
              <span>Reason</span>
              <input autoFocus onChange={(e) => setReason(e.target.value)} value={reason} />
            </label>
            <div className="form-grid__wide modal-actions">
              <button className="secondary-button" disabled={busy} onClick={() => setCancelling(null)} type="button">
                Keep it
              </button>
              <button
                className="primary-button primary-button--danger"
                disabled={busy || !reason.trim()}
                onClick={() => void confirmCancel()}
                type="button"
              >
                Cancel referral
              </button>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
