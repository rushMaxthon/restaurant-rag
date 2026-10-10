/**
 * The platform's own delivery riders: who they are, who is out right now,
 * what they are paid, and marking that pay sent.
 *
 * ADMIN only, like every `/api/admin/riders` route: the fleet is shared by
 * every restaurant, and an owner who could read it could see the others'
 * deliveries. Owners only ever see "rider assigned" on their own orders.
 *
 * Riders either sign up in the rider app and are approved on the
 * Applications tab, or are added here with a mobile number and password.
 * There is no delete - trips and
 * payouts point at the account - so a rider who leaves is deactivated, which
 * signs them out at once and withdraws any order they were being offered.
 */

import { dueForRefresh, firstTab } from '../services/riderApplications';
import { Bike, ClipboardCheck, Map as MapIcon, MapPin, Pencil, Plus, Power, Save, Settings2, Trash2, UserPlus, Users, Wallet } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { ApplicationsTab } from '../components/riders/ApplicationsTab';
import { useRidersChanged } from '../hooks/useRealtime';
import { DataToolbar } from '../components/DataToolbar';
import { EmptyPanel } from '../components/EmptyPanel';
import { Modal } from '../components/Modal';
import { PageIntro } from '../components/PageIntro';
import { RiderLiveMap } from '../components/RiderLiveMap';
import { ResponsiveTable, type TableColumn } from '../components/ResponsiveTable';
import { StatusPill } from '../components/StatusPill';
import { useMoney } from '../hooks/useMoney';
import { ApiError, api } from '../services/api';
import {
  VEHICLE_LABEL,
  branchScopeLabel,
  emptyRiderDraft,
  lastSeenLabel,
  payDraftFrom,
  payExample,
  payFormError,
  payFromDraft,
  riderFormErrors,
  type PayDraft,
  tenDigits,
  toggleBranch,
  type RiderDraft,
} from '../services/riders';
import type { FleetConfig, FleetSettings, Rider, RiderTripToPrice, RiderUnpaid, ToastMessage } from '../types/app';

interface RidersPageProps {
  token: string;
  onNavigate?: (path: string) => void;
  onToast: (title: string, description: string, tone?: ToastMessage['tone']) => void;
}

type Tab = 'applications' | 'map' | 'roster' | 'settings' | 'payouts';
type StatusFilter = 'ALL' | 'ONLINE' | 'ON_TRIP' | 'OFFLINE' | 'INACTIVE';

const TABS: { key: Tab; label: string; icon: typeof Users }[] = [
  { key: 'map', label: 'Live map', icon: MapIcon },
  { key: 'applications', label: 'Applications', icon: ClipboardCheck },
  { key: 'roster', label: 'Riders', icon: Users },
  { key: 'settings', label: 'Pay & dispatch', icon: Settings2 },
  { key: 'payouts', label: 'Payouts', icon: Wallet },
];

/** The pill's words: a rider who is offline is simply off shift, not broken. */
function riderStatus(rider: Rider): string {
  if (!rider.is_active) return 'INACTIVE';
  if (rider.status === 'OFFLINE') return 'OFF SHIFT';
  if (rider.status === 'ON_TRIP') return 'ON TRIP';
  return rider.status;
}

function tabFromAddress(): Tab | null {
  const asked = new URLSearchParams(window.location.search).get('tab');
  return TABS.some((t) => t.key === asked) ? (asked as Tab) : null;
}

export function RidersPage({ token, onToast, onNavigate }: RidersPageProps) {
  // `?tab=` is how the review page's back button returns to the queue.
  const [picked, setPicked] = useState<Tab | null>(tabFromAddress);
  const waiting = useSubmittedCount(token);
  // Somebody waiting to be approved comes before the map: it is the one
  // thing on this page that only an admin can move forward. Decided once,
  // from the first count - never again while the page is open, or the page
  // switched tabs under an admin watching the map whenever someone applied.
  // Null until the count is in when nothing was asked for, so the map does
  // not mount for a moment and then give way to the queue.
  const [settled, setSettled] = useState<Tab | null>(null);
  // Adjusting state while rendering (React's pattern for "derive once from a
  // prop"), not in an effect: no extra render with the wrong tab.
  if (settled === null && waiting !== null) setSettled(firstTab(waiting));
  const tab: Tab | null = picked ?? settled;
  const queueFirst = settled === 'applications';
  const tabs = queueFirst ? [TABS[1], TABS[0], ...TABS.slice(2)] : [...TABS.slice(0, 1), ...TABS.slice(2), TABS[1]];

  const choose = (key: Tab) => {
    setPicked(key);
    // Replaced, not pushed: switching tabs is not a page the back button
    // should step through, but a reload should land on the same tab.
    window.history.replaceState(window.history.state, '', key === 'map' ? '/riders' : `/riders?tab=${key}`);
  };

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Platform"
        title="Delivery riders"
        description="The platform's own riders. Orders are offered to the nearest one online; if nobody takes it, the courier does."
      />
      <nav className="segmented-tabs" aria-label="Rider sections">
        {tabs.map(({ key, label, icon: Icon }) => (
          <button
            aria-current={tab === key ? 'page' : undefined}
            className={tab === key ? 'segmented-tabs__item segmented-tabs__item--active' : 'segmented-tabs__item'}
            key={key}
            onClick={() => choose(key)}
            type="button"
          >
            <Icon size={16} strokeWidth={2.1} />
            <span>{label}</span>
            {key === 'applications' && waiting ? (
              <span aria-label={`${waiting} waiting for review`} className="rapp-count rapp-count--alert">
                {waiting}
              </span>
            ) : null}
          </button>
        ))}
      </nav>
      {tab === 'applications' ? <ApplicationsTab onNavigate={onNavigate} token={token} /> : null}
      {tab === 'map' ? <RiderLiveMap onNavigate={onNavigate} onToast={onToast} token={token} /> : null}
      {tab === 'roster' ? <RosterTab onToast={onToast} token={token} /> : null}
      {tab === 'settings' ? <SettingsTab onToast={onToast} token={token} /> : null}
      {tab === 'payouts' ? <PayoutsTab onToast={onToast} token={token} /> : null}
    </div>
  );
}

/**
 * How many applications are waiting for review, for the tab's badge. Null
 * until the first answer; zero on an error, because a badge is a nudge and a
 * failed count is not worth an error on a page whose other tabs work.
 */
function useSubmittedCount(token: string): number | null {
  const [count, setCount] = useState<number | null>(null);
  const lastAt = useRef(0);
  const load = useCallback(() => {
    lastAt.current = Date.now();
    api
      .listRiderApplications(token, { status: 'SUBMITTED' })
      .then((rows) => setCount(rows.length))
      .catch(() => setCount((current) => current ?? 0));
  }, [token]);
  useEffect(() => {
    load();
    const id = window.setInterval(load, 60_000);
    return () => window.clearInterval(id);
  }, [load]);
  // The hint also fires on every rider's location ping: refetch at most
  // every 15 s on it, not a 500-row query per ping per open tab.
  useRidersChanged(() => {
    if (dueForRefresh(lastAt.current, Date.now(), 15_000)) load();
  });
  return count;
}

// --- Roster -----------------------------------------------------------------------

function RosterTab({ token, onToast }: RidersPageProps) {
  const [riders, setRiders] = useState<Rider[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState<StatusFilter>('ALL');
  const [editing, setEditing] = useState<Rider | 'new' | null>(null);
  const [pendingDeactivate, setPendingDeactivate] = useState<Rider | null>(null);
  const [togglingId, setTogglingId] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listRiders(token)
      .then((rows) => {
        setRiders(rows);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token]);

  // Live status moves on its own: refreshed the moment a rider goes online,
  // offline, takes an order or finishes one (fleet:riders_changed), and
  // polled while the page is open in case a push is missed.
  useEffect(() => {
    load();
    const id = window.setInterval(load, 20_000);
    return () => window.clearInterval(id);
  }, [load, reload]);
  useRidersChanged(load);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (riders ?? []).filter((rider) => {
      if (status === 'INACTIVE' ? rider.is_active : status !== 'ALL' && (!rider.is_active || rider.status !== status)) return false;
      if (!q) return true;
      return [rider.full_name, rider.phone_number ?? '', rider.vehicle_number, rider.city]
        .join(' ')
        .toLowerCase()
        .includes(q);
    });
  }, [riders, query, status]);

  const counts = useMemo(() => {
    const all = riders ?? [];
    return {
      online: all.filter((r) => r.is_active && r.status === 'ONLINE').length,
      onTrip: all.filter((r) => r.is_active && r.status === 'ON_TRIP').length,
      total: all.filter((r) => r.is_active).length,
    };
  }, [riders]);

  const setActive = async (rider: Rider, active: boolean) => {
    setTogglingId(rider.user_id);
    try {
      await api.updateRider(token, rider.user_id, { is_active: active });
      onToast(
        active ? 'Rider reactivated' : 'Rider deactivated',
        active
          ? `${rider.full_name} can sign into the rider app again.`
          : `${rider.full_name} has been signed out and will get no more orders.`,
        'success',
      );
      load();
    } catch (e: unknown) {
      onToast('Could not change the rider', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setTogglingId(null);
    }
  };

  const columns: Array<TableColumn<Rider>> = [
    {
      id: 'rider',
      header: 'Rider',
      render: (row) => (
        <div className="usr-cell">
          <div className="usr-cell__copy">
            <strong>{row.full_name}</strong>
            <span>{row.phone_number}</span>
          </div>
        </div>
      ),
      mobileLabel: 'Rider',
      hideOnMobile: true,
    },
    {
      id: 'status',
      header: 'Status',
      render: (row) => <StatusPill status={riderStatus(row)} />,
      mobileLabel: 'Status',
    },
    {
      id: 'vehicle',
      header: 'Vehicle',
      render: (row) => (
        <span className="kds-branch">
          <Bike size={12} strokeWidth={2.2} />
          {VEHICLE_LABEL[row.vehicle_type]}
          {row.vehicle_number ? ` · ${row.vehicle_number}` : ''}
        </span>
      ),
      mobileLabel: 'Vehicle',
    },
    {
      id: 'seen',
      header: 'Last seen',
      render: (row) =>
        row.last_latitude !== null && row.last_longitude !== null ? (
          <a
            className="kds-branch"
            href={`https://www.google.com/maps?q=${row.last_latitude},${row.last_longitude}`}
            rel="noreferrer"
            target="_blank"
            title="Open where the rider was last seen"
          >
            <MapPin size={12} strokeWidth={2.2} />
            {lastSeenLabel(row.last_location_at)}
          </a>
        ) : (
          <span className="hint-text">Never</span>
        ),
      mobileLabel: 'Last seen',
    },
    {
      id: 'city',
      header: 'City',
      render: (row) => row.city || '—',
      mobileLabel: 'City',
    },
  ];

  return (
    <>
      <section className="admin-surface">
        <DataToolbar
          actions={
            <>
              <span className="toolbar-meta">
                {counts.online} online · {counts.onTrip} on a trip · {counts.total} active
              </span>
              <button className="primary-button" onClick={() => setEditing('new')} type="button">
                <UserPlus size={16} strokeWidth={2.2} />
                Add rider
              </button>
            </>
          }
          filters={
            <select
              className="page-search page-search--select"
              onChange={(event) => setStatus(event.target.value as StatusFilter)}
              value={status}
            >
              <option value="ALL">All riders</option>
              <option value="ONLINE">Online</option>
              <option value="ON_TRIP">On a trip</option>
              <option value="OFFLINE">Offline</option>
              <option value="INACTIVE">Deactivated</option>
            </select>
          }
          onSearchChange={setQuery}
          searchPlaceholder="Filter by name, phone, vehicle or city"
          searchValue={query}
        />
        <ResponsiveTable
          actions={[
            { id: 'edit', label: 'Edit rider', icon: Pencil, onClick: (row: Rider) => setEditing(row) },
            {
              id: 'deactivate',
              label: 'Deactivate rider',
              icon: Power,
              onClick: (row: Rider) => setPendingDeactivate(row),
              hidden: (row: Rider) => !row.is_active,
              disabled: (row: Rider) => togglingId === row.user_id || row.status === 'ON_TRIP',
              tone: 'danger' as const,
            },
            {
              id: 'activate',
              label: 'Reactivate rider',
              icon: Power,
              onClick: (row: Rider) => void setActive(row, true),
              hidden: (row: Rider) => row.is_active,
              disabled: (row: Rider) => togglingId === row.user_id,
              tone: 'success' as const,
            },
          ]}
          columns={columns}
          emptyAction={
            <button className="primary-button" onClick={() => setEditing('new')} type="button">
              Add rider
            </button>
          }
          emptyDescription={
            query || status !== 'ALL'
              ? 'Try a different status or search.'
              : 'Add your first rider. They sign into the Foodie Rider app with the mobile number and password you set.'
          }
          emptyTitle={query || status !== 'ALL' ? 'No riders match' : 'No riders yet'}
          error={error}
          errorTitle="We couldn't load riders"
          keyExtractor={(row) => row.user_id}
          loading={riders === null && !error}
          mobileStatus={(row) => <StatusPill status={riderStatus(row)} />}
          mobileSubtitle={(row) => `${row.phone_number ?? ''} · ${VEHICLE_LABEL[row.vehicle_type]}`}
          mobileTitle={(row) => row.full_name}
          onRetry={() => setReload((n) => n + 1)}
          rows={filtered}
        />
      </section>

      {editing ? (
        <RiderEditor
          onClose={() => setEditing(null)}
          onSaved={(name, created) => {
            setEditing(null);
            onToast(
              created ? 'Rider added' : 'Rider updated',
              created ? `${name} can now sign into the rider app.` : `${name}'s details are saved.`,
              'success',
            );
            load();
          }}
          rider={editing === 'new' ? null : editing}
          token={token}
        />
      ) : null}

      {pendingDeactivate ? (
        <ConfirmDialog
          open
          confirmLabel="Deactivate"
          description={`${pendingDeactivate.full_name} will be signed out of the rider app immediately and get no more orders. Their trip history and pay are kept.`}
          onCancel={() => setPendingDeactivate(null)}
          onConfirm={() => {
            const rider = pendingDeactivate;
            setPendingDeactivate(null);
            void setActive(rider, false);
          }}
          title="Deactivate this rider?"
          tone="danger"
        />
      ) : null}
    </>
  );
}

function RiderEditor({
  token,
  rider,
  onClose,
  onSaved,
}: {
  token: string;
  rider: Rider | null;
  onClose: () => void;
  onSaved: (name: string, created: boolean) => void;
}) {
  const mode = rider ? 'edit' : 'create';
  const [draft, setDraft] = useState<RiderDraft>(() =>
    rider
      ? {
          full_name: rider.full_name,
          phone: tenDigits(rider.phone_number ?? ''),
          password: '',
          vehicle_type: rider.vehicle_type,
          vehicle_number: rider.vehicle_number,
          city: rider.city,
          notes: rider.notes,
        }
      : emptyRiderDraft(),
  );
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const errors = riderFormErrors(draft, mode);
  const invalid = Object.keys(errors).length > 0;

  const set = <K extends keyof RiderDraft>(key: K, value: RiderDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setServerError(null);
  };

  async function save() {
    setTouched(true);
    if (invalid) return;
    setBusy(true);
    try {
      if (rider) {
        await api.updateRider(token, rider.user_id, {
          full_name: draft.full_name.trim(),
          vehicle_type: draft.vehicle_type,
          vehicle_number: draft.vehicle_number.trim(),
          city: draft.city.trim(),
          notes: draft.notes,
          ...(draft.password ? { password: draft.password } : {}),
        });
      } else {
        await api.createRider(token, {
          full_name: draft.full_name.trim(),
          phone_number: tenDigits(draft.phone),
          password: draft.password,
          vehicle_type: draft.vehicle_type,
          vehicle_number: draft.vehicle_number.trim(),
          city: draft.city.trim(),
          notes: draft.notes,
        });
      }
      onSaved(draft.full_name.trim(), !rider);
    } catch (e: unknown) {
      setServerError(e instanceof ApiError ? e.message : 'Could not save. Please try again.');
    } finally {
      setBusy(false);
    }
  }

  const show = (key: keyof RiderDraft) => (touched ? errors[key] : undefined);

  return (
    <Modal busy={busy} className="modal-card--compact" labelledBy="rider-editor-title" onClose={onClose}>
      <div className="panel__header modal-card__header">
        <div>
          <span className="eyebrow">Rider</span>
          <h2 id="rider-editor-title">{rider ? `Edit ${rider.full_name}` : 'Add a rider'}</h2>
          <p className="hint-text">
            {rider
              ? 'Changing the password signs the rider out of the app.'
              : 'They sign into the Foodie Rider app with this mobile number and password.'}
          </p>
        </div>
        <button aria-label="Close" className="modal-close" onClick={onClose} type="button">
          ×
        </button>
      </div>
      <div className="form-grid modal-card__body">
        <label className="field form-grid__wide">
          <span>Full name</span>
          <input autoFocus onChange={(e) => set('full_name', e.target.value)} value={draft.full_name} />
          {show('full_name') ? <small className="field__error">{show('full_name')}</small> : null}
        </label>
        <label className="field">
          <span>Mobile number</span>
          <input
            disabled={Boolean(rider)}
            inputMode="tel"
            onChange={(e) => set('phone', e.target.value)}
            placeholder="98765 43210"
            value={draft.phone}
          />
          {rider ? <small>The login number cannot change. Add a new rider for a new number.</small> : null}
          {show('phone') ? <small className="field__error">{show('phone')}</small> : null}
        </label>
        <label className="field">
          <span>{rider ? 'New password' : 'Password'}</span>
          <input
            autoComplete="new-password"
            onChange={(e) => set('password', e.target.value)}
            placeholder={rider ? 'Leave empty to keep it' : 'At least 8 characters'}
            type="password"
            value={draft.password}
          />
          {show('password') ? <small className="field__error">{show('password')}</small> : null}
        </label>
        <label className="field">
          <span>Vehicle</span>
          <select onChange={(e) => set('vehicle_type', e.target.value as RiderDraft['vehicle_type'])} value={draft.vehicle_type}>
            {(Object.keys(VEHICLE_LABEL) as RiderDraft['vehicle_type'][]).map((key) => (
              <option key={key} value={key}>
                {VEHICLE_LABEL[key]}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Number plate</span>
          <input onChange={(e) => set('vehicle_number', e.target.value.toUpperCase())} placeholder="GJ05AB1234" value={draft.vehicle_number} />
        </label>
        <label className="field">
          <span>City</span>
          <input onChange={(e) => set('city', e.target.value)} placeholder="Surat" value={draft.city} />
        </label>
        <label className="field form-grid__wide">
          <span>Notes (only admins see these)</span>
          <textarea onChange={(e) => set('notes', e.target.value)} rows={2} value={draft.notes} />
        </label>
        {serverError ? (
          <p className="field__error form-grid__wide" role="alert">
            {serverError}
          </p>
        ) : null}
        <div className="form-grid__wide modal-actions">
          <button className="secondary-button" disabled={busy} onClick={onClose} type="button">
            Cancel
          </button>
          <button className="primary-button" disabled={busy || (touched && invalid)} onClick={() => void save()} type="button">
            {rider ? <Save size={15} /> : <UserPlus size={15} />}
            {busy ? 'Saving…' : rider ? 'Save rider' : 'Add rider'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

// --- Pay & dispatch ------------------------------------------------------------

function SettingsTab({ token, onToast }: RidersPageProps) {
  const money = useMoney();
  const [saved, setSaved] = useState<FleetSettings | null>(null);
  const [pay, setPay] = useState<PayDraft | null>(null);
  const [fleet, setFleet] = useState<FleetConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'pay' | 'fleet' | null>(null);

  useEffect(() => {
    api
      .getFleetSettings(token)
      .then((settings) => {
        setSaved(settings);
        setPay(payDraftFrom(settings.pay));
        setFleet(settings.fleet);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token]);

  if (error) {
    return (
      <section className="admin-surface">
        <EmptyPanel description={error} title="Rider settings didn't load" />
      </section>
    );
  }
  if (!saved || !pay || !fleet) {
    return (
      <section className="admin-surface">
        <p className="hint-text">Loading rider settings…</p>
      </section>
    );
  }

  const payError = payFormError(pay);
  const payDirty = JSON.stringify(pay) !== JSON.stringify(payDraftFrom(saved.pay));
  const fleetDirty = JSON.stringify(fleet) !== JSON.stringify(saved.fleet);

  async function savePay() {
    if (!pay || payError) return;
    setBusy('pay');
    try {
      const next = await api.saveRiderPay(token, payFromDraft(pay));
      setSaved(next);
      setPay(payDraftFrom(next.pay));
      onToast('Rider pay saved', 'New rates apply to trips that end from now on.', 'success');
    } catch (e: unknown) {
      onToast('Could not save pay', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(null);
    }
  }

  async function saveFleet() {
    if (!fleet) return;
    setBusy('fleet');
    try {
      const next = await api.saveFleetConfig(token, fleet);
      setSaved(next);
      setFleet(next.fleet);
      onToast('Dispatch settings saved', 'The next order uses them.', 'success');
    } catch (e: unknown) {
      onToast('Could not save', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(null);
    }
  }

  const number = (key: keyof Omit<FleetConfig, 'location_ids'>) => (event: React.ChangeEvent<HTMLInputElement>) =>
    setFleet({ ...fleet, [key]: event.target.value === '' ? 0 : Number(event.target.value) });

  const examples = [2, 4, 7, 9].map((km) => ({ km, pay: payExample(pay, km) }));
  const lastKm = pay.slabs.length ? pay.slabs[pay.slabs.length - 1].up_to_km || '?' : '?';
  const editSlab = (index: number, field: 'up_to_km' | 'amount', value: string) =>
    setPay({ ...pay, slabs: pay.slabs.map((slab, at) => (at === index ? { ...slab, [field]: value } : slab)) });
  const slabLabel = (index: number) => {
    const to = pay.slabs[index].up_to_km || '?';
    return index === 0 ? `Up to ${to} km` : `${pay.slabs[index - 1].up_to_km || '?'} – ${to} km`;
  };
  const addSlab = () => {
    const last = pay.slabs[pay.slabs.length - 1];
    const km = last ? Number(last.up_to_km) + 0.5 : 3;
    setPay({ ...pay, slabs: [...pay.slabs, { up_to_km: String(Number.isFinite(km) ? km : ''), amount: last?.amount ?? '' }] });
  };

  return (
    <>
      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Status</span>
            <h2>{saved.enabled ? 'Riders are getting orders' : 'Riders are not getting orders yet'}</h2>
            <p className="hint-text">
              {saved.enabled
                ? 'New delivery orders are offered to your riders first, and go to the courier when nobody takes them.'
                : 'Switched off on the server (ENABLE_OWN_FLEET). Riders can sign in and practise; every delivery still goes to the courier.'}
            </p>
          </div>
          <StatusPill status={saved.enabled ? 'ENABLED' : 'DISABLED'} />
        </div>
      </section>

      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Pay per delivery</span>
            <h2>Rider rate card</h2>
            <p className="hint-text">
              A trip pays the slab its distance falls in, plus the incentive for every successful delivery. Past{' '}
              {lastKm} km there is no rate: you set that trip&rsquo;s pay on the Payouts tab. Customers&rsquo; delivery
              fees are set separately, on Delivery pricing.
            </p>
          </div>
        </div>
        <div className="delivery-slabs">
          {pay.slabs.map((slab, index) => (
            <div className="delivery-slab" key={index}>
              <strong className="delivery-slab__range">{slabLabel(index)}</strong>
              <label className="field">
                <span>Up to (km)</span>
                <input
                  disabled={busy !== null}
                  inputMode="decimal"
                  min={0}
                  onChange={(e) => editSlab(index, 'up_to_km', e.target.value)}
                  step="0.5"
                  type="number"
                  value={slab.up_to_km}
                />
              </label>
              <label className="field">
                <span>Rider gets (₹)</span>
                <input
                  disabled={busy !== null}
                  inputMode="decimal"
                  min={0}
                  onChange={(e) => editSlab(index, 'amount', e.target.value)}
                  step="1"
                  type="number"
                  value={slab.amount}
                />
              </label>
              <div className="delivery-slab__paid">
                <span>With incentive</span>
                <strong className="money">
                  {Number.isFinite(Number(slab.amount) + Number(pay.incentive)) && slab.amount !== ''
                    ? money.format(Number(slab.amount) + Number(pay.incentive || 0))
                    : '—'}
                </strong>
              </div>
              <button
                aria-label={`Remove ${slabLabel(index)}`}
                className="secondary-button delivery-slab__remove"
                disabled={busy !== null || pay.slabs.length <= 1}
                onClick={() => setPay({ ...pay, slabs: pay.slabs.filter((_, at) => at !== index) })}
                title={pay.slabs.length <= 1 ? 'There must always be one slab.' : 'Remove this slab'}
                type="button"
              >
                <Trash2 size={15} />
              </button>
            </div>
          ))}
        </div>
        <button className="secondary-button" disabled={busy !== null} onClick={addSlab} type="button">
          <Plus size={15} /> Add a slab
        </button>
        <div className="form-grid">
          <label className="field">
            <span>Incentive per delivery (₹)</span>
            <input inputMode="decimal" min={0} onChange={(e) => setPay({ ...pay, incentive: e.target.value })} type="number" value={pay.incentive} />
            <small>Added on top for every successful delivery - not for a cancelled trip or a door nobody opened.</small>
          </label>
          <label className="field">
            <span>Cancelled after reaching the restaurant (₹)</span>
            <input inputMode="decimal" min={0} onChange={(e) => setPay({ ...pay, minimum: e.target.value })} type="number" value={pay.minimum} />
            <small>The rider rode there for nothing. Cancelled before they arrived pays nothing.</small>
          </label>
          <div className="field">
            <span>Examples (delivered)</span>
            <small>
              {examples
                .map((e) => `${e.km} km → ${e.pay === null ? '—' : e.pay === 'manual' ? 'you set it' : money.format(e.pay)}`)
                .join(' · ')}
            </small>
          </div>
        </div>
        {payError ? <p role="alert">{payError}</p> : null}
        <div className="modal-actions">
          <button className="primary-button" disabled={!payDirty || Boolean(payError) || busy !== null} onClick={() => void savePay()} type="button">
            <Save size={15} /> {busy === 'pay' ? 'Saving…' : 'Save pay'}
          </button>
        </div>
      </section>

      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Dispatch</span>
            <h2>How orders are offered</h2>
            <p className="hint-text">
              One rider at a time, nearest first. On the Orders board the nearest riders see an order first, and it
              reaches one ring further out every few minutes nobody takes it. Only when the window ends does the courier
              take it.
            </p>
          </div>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>Seconds to accept</span>
            <input max={120} min={10} onChange={number('offer_seconds')} type="number" value={fleet.offer_seconds} />
          </label>
          <label className="field">
            <span>Riders to ring</span>
            <input max={20} min={1} onChange={number('max_offers')} type="number" value={fleet.max_offers} />
            <small>After this many, nobody is rung again; the order stays on the Orders board.</small>
          </label>
          <label className="field">
            <span>Minutes before the courier takes it</span>
            <input max={30} min={1} onChange={number('window_minutes')} type="number" value={fleet.window_minutes} />
            <small>Our riders get this long first. Cash orders always go to the courier.</small>
          </label>
          <label className="field">
            <span>Search radius (km)</span>
            <input max={25} min={0.5} onChange={number('radius_km')} step="0.5" type="number" value={fleet.radius_km} />
          </label>
          <label className="field">
            <span>First ring (km)</span>
            <input max={25} min={0.5} onChange={number('first_wave_km')} step="0.5" type="number" value={fleet.first_wave_km} />
            <small>Riders this close to the restaurant see a new order first. Each ring adds this much again.</small>
          </label>
          <label className="field">
            <span>Minutes per ring</span>
            <input max={10} min={1} onChange={number('wave_minutes')} type="number" value={fleet.wave_minutes} />
            <small>Nobody takes it in this long, and riders one ring further out see it too.</small>
          </label>
          <label className="field">
            <span>Send to riders before food is ready (minutes)</span>
            <input max={60} min={0} onChange={number('ready_lead_minutes')} type="number" value={fleet.ready_lead_minutes} />
            <small>
              Uses each branch&apos;s preparation time. A branch without one sends the order to riders at once.
            </small>
          </label>
          <label className="field">
            <span>Offline after silent (minutes)</span>
            <input max={30} min={1} onChange={number('silent_minutes')} type="number" value={fleet.silent_minutes} />
            <small>A rider whose phone stops sending a location is taken offline.</small>
          </label>
          <label className="field">
            <span>Keep a closed app on shift (minutes)</span>
            <input max={60} min={0} onChange={number('push_minutes')} type="number" value={fleet.push_minutes} />
            <small>
              If the app is closed, orders still reach the rider by notification for this long, after riders whose
              phones are reporting. Then their shift ends and they are told. 0 turns this off.
            </small>
          </label>
        </div>
        <fieldset className="field checkbox-set rider-branches">
          <legend>
            Branches our riders serve <strong>· {branchScopeLabel(fleet.location_ids, saved.branches)}</strong>
          </legend>
          <small>
            Leave every box empty to serve every branch. Tick some to start city by city; the rest go straight to the
            courier.
          </small>
          {saved.branches.length === 0 ? (
            <p className="hint-text">No active branches yet.</p>
          ) : (
            <div className="rider-branches__list">
              {saved.branches.map((branch) => (
                <label className="rider-branches__item" key={branch.id}>
                  <input
                    checked={fleet.location_ids.includes(branch.id)}
                    onChange={() => setFleet({ ...fleet, location_ids: toggleBranch(fleet.location_ids, branch.id) })}
                    type="checkbox"
                  />
                  <span>
                    {branch.restaurant_name} · {branch.branch_name}
                    <small>
                      {branch.city}
                      {branch.delivery_enabled ? '' : ' · delivery off'}
                    </small>
                  </span>
                </label>
              ))}
            </div>
          )}
          {fleet.location_ids.length > 0 ? (
            <button className="secondary-button" onClick={() => setFleet({ ...fleet, location_ids: [] })} type="button">
              Serve every branch
            </button>
          ) : null}
        </fieldset>
        <div className="modal-actions">
          <button className="secondary-button" disabled={!fleetDirty || busy !== null} onClick={() => setFleet(saved.fleet)} type="button">
            Discard
          </button>
          <button className="primary-button" disabled={!fleetDirty || busy !== null} onClick={() => void saveFleet()} type="button">
            <Save size={15} /> {busy === 'fleet' ? 'Saving…' : 'Save dispatch'}
          </button>
        </div>
      </section>
    </>
  );
}

// --- Payouts --------------------------------------------------------------------

/**
 * Trips past the rate card ("above 8 km - manual pricing") end with no
 * amount; the admin types it here. Until then the trip is not in "To be
 * paid", so a payout cannot skip it silently - it is paid in the next one.
 */
function TripsToPrice({ token, onToast, onPriced }: RidersPageProps & { onPriced: () => void }) {
  const money = useMoney();
  const [rows, setRows] = useState<RiderTripToPrice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listTripsToPrice(token)
      .then((list) => {
        setRows(list);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token]);

  useEffect(load, [load]);

  async function price(row: RiderTripToPrice) {
    const amount = (amounts[row.trip_id] ?? '').trim();
    setBusy(row.trip_id);
    try {
      const saved = await api.priceTrip(token, row.trip_id, amount);
      onToast('Trip priced', `${row.rider_name} gets ${money.format(Number(saved.earning_amount))} for ${row.order_code}.`, 'success');
      load();
      onPriced();
    } catch (e: unknown) {
      onToast('Could not save the price', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(null);
    }
  }

  if (error) {
    return (
      <section className="admin-surface">
        <EmptyPanel description={error} title="Trips to price didn't load" />
      </section>
    );
  }
  if (!rows || rows.length === 0) return null;

  return (
    <section className="admin-surface">
      <div className="admin-surface__header">
        <div>
          <span className="eyebrow">Needs a price</span>
          <h2>
            {rows.length} {rows.length === 1 ? 'trip' : 'trips'} past the rate card
          </h2>
          <p className="hint-text">
            Longer than the last slab, so no rate applies. Enter what the rider gets for the distance; the incentive is
            added on top for a delivered trip.
          </p>
        </div>
      </div>
      <div className="delivery-slabs">
        {rows.map((row) => {
          const typed = amounts[row.trip_id] ?? '';
          const valid = typed.trim() !== '' && Number.isFinite(Number(typed)) && Number(typed) >= 0 && Number(typed) <= 5000;
          return (
            <div className="delivery-slab" key={row.trip_id}>
              <strong className="delivery-slab__range">
                {row.rider_name} · {row.order_code}
                <br />
                <small className="hint-text">
                  {row.distance_km ?? '?'} km · {row.delivered ? 'delivered' : 'not delivered'} ·{' '}
                  {new Date(row.ended_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
                </small>
              </strong>
              <label className="field">
                <span>Rider gets (₹)</span>
                <input
                  disabled={busy !== null}
                  inputMode="decimal"
                  min={0}
                  onChange={(e) => setAmounts({ ...amounts, [row.trip_id]: e.target.value })}
                  type="number"
                  value={typed}
                />
              </label>
              <div className="delivery-slab__paid">
                <span>{Number(row.incentive) > 0 ? `+ ${money.format(Number(row.incentive))} incentive` : 'No incentive'}</span>
                <strong className="money">{valid ? money.format(Number(typed) + Number(row.incentive)) : '—'}</strong>
              </div>
              <button className="primary-button" disabled={!valid || busy !== null} onClick={() => void price(row)} type="button">
                <Save size={15} /> {busy === row.trip_id ? 'Saving…' : 'Set pay'}
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function PayoutsTab({ token, onToast }: RidersPageProps) {
  const money = useMoney();
  const [rows, setRows] = useState<RiderUnpaid[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [paying, setPaying] = useState<RiderUnpaid | null>(null);
  const [reference, setReference] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .listUnpaidRiders(token)
      .then((list) => {
        setRows(list);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token]);

  useEffect(load, [load]);

  async function confirmPay() {
    if (!paying) return;
    setBusy(true);
    try {
      const payout = await api.payRider(token, paying.rider_user_id, {
        period_to: new Date().toISOString(),
        reference: reference.trim(),
      });
      onToast('Marked as paid', `${money.format(Number(payout.amount))} for ${payout.trips} trips to ${paying.full_name}.`, 'success');
      setPaying(null);
      setReference('');
      load();
    } catch (e: unknown) {
      onToast('Could not mark paid', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(false);
    }
  }

  const total = (rows ?? []).reduce((sum, row) => sum + Number(row.amount), 0);

  const columns: Array<TableColumn<RiderUnpaid>> = [
    { id: 'rider', header: 'Rider', render: (row) => <strong>{row.full_name}</strong>, mobileLabel: 'Rider', hideOnMobile: true },
    { id: 'trips', header: 'Unpaid trips', render: (row) => row.trips, mobileLabel: 'Trips' },
    { id: 'amount', header: 'Amount', render: (row) => <strong className="money">{money.format(Number(row.amount))}</strong>, mobileLabel: 'Amount' },
    {
      id: 'since',
      header: 'Oldest unpaid',
      render: (row) => (row.oldest ? new Date(row.oldest).toLocaleDateString(undefined, { dateStyle: 'medium' }) : '—'),
      mobileLabel: 'Since',
    },
  ];

  return (
    <>
      <TripsToPrice onPriced={load} onToast={onToast} token={token} />
      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">To be paid</span>
            <h2>{money.format(total)} owed to riders</h2>
            <p className="hint-text">Pay each rider by bank transfer, then mark it paid here so their app shows it.</p>
          </div>
        </div>
        <ResponsiveTable
          actions={[
            {
              id: 'pay',
              label: 'Mark paid',
              icon: Wallet,
              onClick: (row: RiderUnpaid) => setPaying(row),
              tone: 'success' as const,
            },
          ]}
          columns={columns}
          emptyDescription="Every finished trip has been paid. New trips show up here when they end."
          emptyTitle="Nothing to pay"
          error={error}
          errorTitle="We couldn't load payouts"
          keyExtractor={(row) => row.rider_user_id}
          loading={rows === null && !error}
          mobileStatus={(row) => <strong className="money">{money.format(Number(row.amount))}</strong>}
          mobileSubtitle={(row) => `${row.trips} unpaid trips`}
          mobileTitle={(row) => row.full_name}
          onRetry={load}
          rows={rows ?? []}
        />
      </section>

      {paying ? (
        <Modal busy={busy} className="modal-card--compact" labelledBy="pay-rider-title" onClose={() => setPaying(null)}>
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">Payout</span>
              <h2 id="pay-rider-title">Mark {paying.full_name} as paid</h2>
              <p className="hint-text">
                Send {money.format(Number(paying.amount))} to the rider&rsquo;s bank first; this records it and clears{' '}
                {paying.trips} trips.
              </p>
            </div>
            <button aria-label="Close" className="modal-close" onClick={() => setPaying(null)} type="button">
              ×
            </button>
          </div>
          <div className="form-grid modal-card__body">
            <label className="field form-grid__wide">
              <span>Bank reference (UTR), optional</span>
              <input autoFocus onChange={(e) => setReference(e.target.value)} placeholder="e.g. UTR 4567 1234" value={reference} />
            </label>
            <div className="form-grid__wide modal-actions">
              <button className="secondary-button" disabled={busy} onClick={() => setPaying(null)} type="button">
                Cancel
              </button>
              <button className="primary-button" disabled={busy} onClick={() => void confirmPay()} type="button">
                <Wallet size={15} /> {busy ? 'Saving…' : `Mark ${money.format(Number(paying.amount))} paid`}
              </button>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
