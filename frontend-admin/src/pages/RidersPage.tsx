/**
 * The platform's own delivery riders: who they are, who is out right now,
 * what they are paid, and marking that pay sent.
 *
 * ADMIN only, like every `/api/admin/riders` route: the fleet is shared by
 * every restaurant, and an owner who could read it could see the others'
 * deliveries. Owners only ever see "rider assigned" on their own orders.
 *
 * Riders sign into the rider app with the mobile number and password set
 * here; there is no self-signup. There is no delete either - trips and
 * payouts point at the account - so a rider who leaves is deactivated, which
 * signs them out at once and withdraws any order they were being offered.
 */

import { Bike, Map as MapIcon, MapPin, Pencil, Power, Save, Settings2, UserPlus, Users, Wallet } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
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
  payExample,
  payFormError,
  riderFormErrors,
  tenDigits,
  toggleBranch,
  type RiderDraft,
} from '../services/riders';
import type { FleetConfig, FleetSettings, Rider, RiderPay, RiderUnpaid, ToastMessage } from '../types/app';

interface RidersPageProps {
  token: string;
  onNavigate?: (path: string) => void;
  onToast: (title: string, description: string, tone?: ToastMessage['tone']) => void;
}

type Tab = 'map' | 'roster' | 'settings' | 'payouts';
type StatusFilter = 'ALL' | 'ONLINE' | 'ON_TRIP' | 'OFFLINE' | 'INACTIVE';

const TABS: { key: Tab; label: string; icon: typeof Users }[] = [
  { key: 'map', label: 'Live map', icon: MapIcon },
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

export function RidersPage({ token, onToast, onNavigate }: RidersPageProps) {
  const [tab, setTab] = useState<Tab>('map');

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Platform"
        title="Delivery riders"
        description="The platform's own riders. Orders are offered to the nearest one online; if nobody takes it, the courier does."
      />
      <nav className="segmented-tabs" aria-label="Rider sections">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            className={tab === key ? 'segmented-tabs__item segmented-tabs__item--active' : 'segmented-tabs__item'}
            key={key}
            onClick={() => setTab(key)}
            type="button"
          >
            <Icon size={16} strokeWidth={2.1} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      {tab === 'map' ? <RiderLiveMap onNavigate={onNavigate} onToast={onToast} token={token} /> : null}
      {tab === 'roster' ? <RosterTab onToast={onToast} token={token} /> : null}
      {tab === 'settings' ? <SettingsTab onToast={onToast} token={token} /> : null}
      {tab === 'payouts' ? <PayoutsTab onToast={onToast} token={token} /> : null}
    </div>
  );
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
  const [pay, setPay] = useState<RiderPay | null>(null);
  const [fleet, setFleet] = useState<FleetConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<'pay' | 'fleet' | null>(null);

  useEffect(() => {
    api
      .getFleetSettings(token)
      .then((settings) => {
        setSaved(settings);
        setPay(settings.pay);
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
  const payDirty = JSON.stringify(pay) !== JSON.stringify(saved.pay);
  const fleetDirty = JSON.stringify(fleet) !== JSON.stringify(saved.fleet);

  async function savePay() {
    if (!pay || payError) return;
    setBusy('pay');
    try {
      const next = await api.saveRiderPay(token, pay);
      setSaved(next);
      setPay(next.pay);
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

  const examples = [2, 4, 7].map((km) => ({ km, pay: payExample(pay, km) }));

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
            <h2>What a rider earns</h2>
            <p className="hint-text">A base amount plus a rate per km of the trip, never less than the minimum.</p>
          </div>
        </div>
        <div className="form-grid">
          <label className="field">
            <span>Base per trip (₹)</span>
            <input inputMode="decimal" onChange={(e) => setPay({ ...pay, base: e.target.value })} type="number" value={pay.base} />
          </label>
          <label className="field">
            <span>Per km (₹)</span>
            <input inputMode="decimal" onChange={(e) => setPay({ ...pay, per_km: e.target.value })} type="number" value={pay.per_km} />
          </label>
          <label className="field">
            <span>Minimum per trip (₹)</span>
            <input inputMode="decimal" onChange={(e) => setPay({ ...pay, minimum: e.target.value })} type="number" value={pay.minimum} />
          </label>
          <div className="field">
            <span>Examples</span>
            <small>
              {examples.map((e) => `${e.km} km → ${e.pay === null ? '—' : money.format(e.pay)}`).join(' · ')}
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
              One rider at a time, nearest first. Anything nobody accepts waits on every rider&apos;s Orders board until the
              window ends; only then does the courier take it.
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
            <span>Offline after silent (minutes)</span>
            <input max={30} min={1} onChange={number('silent_minutes')} type="number" value={fleet.silent_minutes} />
            <small>A rider whose phone stops sending a location is taken offline.</small>
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
