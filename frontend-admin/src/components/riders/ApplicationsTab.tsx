/**
 * The queue of riders who signed up in the app and are waiting to be checked.
 *
 * One request for every application, filtered here: the queue is a few
 * hundred rows at most (the server caps it at 500), and holding all of them is
 * what lets each status button carry its count without five more requests.
 * The order is the server's - oldest submitted first - because the rider who
 * has waited longest should be the first one an admin sees.
 */

import { Bike, ChevronRight, Flag, MapPin } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { useRidersChanged } from '../../hooks/useRealtime';
import { DataToolbar } from '../DataToolbar';
import { ResponsiveTable, type TableColumn } from '../ResponsiveTable';
import { ApiError, api } from '../../services/api';
import { STATUS_META, waitingLabel } from '../../services/riderApplications';
import { VEHICLE_LABEL } from '../../services/riders';
import type { ApplicationStatus, RiderApplicationSummary } from '../../types/app';

interface ApplicationsTabProps {
  token: string;
  onNavigate?: (path: string) => void;
}

/** Drafts last: they are riders still filling the form, with nothing to decide yet. */
const FILTERS: { key: ApplicationStatus; label: string }[] = [
  { key: 'SUBMITTED', label: 'Submitted' },
  { key: 'CHANGES_NEEDED', label: 'Changes needed' },
  { key: 'APPROVED', label: 'Approved' },
  { key: 'REJECTED', label: 'Rejected' },
  { key: 'DRAFT', label: 'Drafts' },
];

const EMPTY: Record<ApplicationStatus, { title: string; description: string }> = {
  SUBMITTED: {
    title: 'Nobody is waiting for review',
    description: 'New sign-ups from the rider app appear here the moment a rider submits.',
  },
  CHANGES_NEEDED: {
    title: 'Nothing sent back',
    description: 'Applications you send back for changes wait here until the rider resubmits.',
  },
  APPROVED: { title: 'No approved applications yet', description: 'Approved riders also appear on the Riders tab.' },
  REJECTED: { title: 'No rejected applications', description: 'A rejection can be reopened from the application.' },
  DRAFT: { title: 'No drafts', description: 'Riders who have signed up but not yet submitted appear here.' },
};

export function ApplicationsTab({ token, onNavigate }: ApplicationsTabProps) {
  const [rows, setRows] = useState<RiderApplicationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<ApplicationStatus>('SUBMITTED');
  const [query, setQuery] = useState('');
  const [city, setCity] = useState('');
  // Re-rendered each minute so "waiting 12 min" does not sit still while the
  // tab is open on a second screen.
  const [now, setNow] = useState(() => new Date());

  const load = useCallback(() => {
    api
      .listRiderApplications(token)
      .then((list) => {
        setRows(list);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token]);

  useEffect(() => {
    load();
    const id = window.setInterval(() => {
      setNow(new Date());
      load();
    }, 60_000);
    return () => window.clearInterval(id);
  }, [load]);
  // A submission and every decision announce `riders_changed`, so a second
  // admin's approval leaves this queue without anybody reloading.
  useRidersChanged(load);

  const counts = useMemo(() => {
    const out: Record<ApplicationStatus, number> = { DRAFT: 0, SUBMITTED: 0, CHANGES_NEEDED: 0, APPROVED: 0, REJECTED: 0 };
    for (const row of rows ?? []) out[row.status] += 1;
    return out;
  }, [rows]);

  const cities = useMemo(
    () => [...new Set((rows ?? []).map((row) => row.city.trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
    [rows],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const digits = q.replace(/\D/g, '');
    return (rows ?? []).filter((row) => {
      if (row.status !== status) return false;
      if (city && row.city.trim().toLowerCase() !== city.toLowerCase()) return false;
      if (!q) return true;
      if (row.full_name.toLowerCase().includes(q)) return true;
      // Phone numbers are stored with +91; somebody types the ten digits.
      return digits.length >= 3 && (row.phone_number ?? '').replace(/\D/g, '').includes(digits);
    });
  }, [rows, status, city, query]);

  const open = (row: RiderApplicationSummary) => onNavigate?.(`/riders/applications/${row.rider_user_id}`);

  const timeLabel = (row: RiderApplicationSummary) =>
    row.status === 'SUBMITTED' ? waitingLabel(row.submitted_at, now) : `${waitingLabel(row.updated_at, now)} ago`;

  const columns: Array<TableColumn<RiderApplicationSummary>> = [
    {
      id: 'rider',
      header: 'Applicant',
      render: (row) => (
        <div className="usr-cell">
          <div className="usr-cell__copy">
            {/* A real link as well as the row click, so the queue can be
                worked from the keyboard and opened in a new tab. */}
            <strong>
            <a
              className="rapp-link"
              href={`/riders/applications/${row.rider_user_id}`}
              onClick={(event) => {
                if (event.metaKey || event.ctrlKey || event.shiftKey) {
                  event.stopPropagation();
                  return;
                }
                event.preventDefault();
                event.stopPropagation();
                open(row);
              }}
            >
              {row.full_name || 'No name yet'}
            </a>
            </strong>
            <span>{row.phone_number ?? '—'}</span>
          </div>
        </div>
      ),
      hideOnMobile: true,
    },
    {
      id: 'vehicle',
      header: 'Vehicle',
      render: (row) =>
        row.vehicle_type ? (
          <span className="kds-branch">
            <Bike size={12} strokeWidth={2.2} />
            {VEHICLE_LABEL[row.vehicle_type]}
          </span>
        ) : (
          <span className="hint-text">Not chosen</span>
        ),
      mobileLabel: 'Vehicle',
    },
    {
      id: 'city',
      header: 'City',
      render: (row) =>
        row.city ? (
          <span className="rapp-inline">
            <MapPin size={13} strokeWidth={2.2} />
            {row.city}
          </span>
        ) : (
          '—'
        ),
      mobileLabel: 'City',
    },
    {
      id: 'status',
      header: 'Status',
      render: (row) => <ApplicationPill status={row.status} />,
      hideOnMobile: true,
    },
    {
      id: 'waiting',
      header: status === 'SUBMITTED' ? 'Waiting' : 'Last change',
      render: (row) => <span className="rapp-waiting">{timeLabel(row)}</span>,
      mobileLabel: status === 'SUBMITTED' ? 'Waiting' : 'Last change',
    },
    {
      id: 'flagged',
      header: 'Flagged',
      render: (row) =>
        row.flagged > 0 ? (
          <span className="rapp-flagged">
            <Flag size={12} strokeWidth={2.4} />
            {row.flagged} flagged
          </span>
        ) : (
          <span className="hint-text">—</span>
        ),
      mobileLabel: 'Flagged',
    },
    {
      id: 'open',
      header: '',
      render: () => <ChevronRight aria-hidden className="rapp-row-chevron" size={16} strokeWidth={2.2} />,
      hideOnMobile: true,
      align: 'right',
    },
  ];

  const filteredOut = Boolean(query || city);

  return (
    <section className="admin-surface">
      <div aria-label="Application status" className="rapp-seg" role="tablist">
        {FILTERS.map(({ key, label }) => (
          <button
            aria-selected={status === key}
            className={status === key ? 'rapp-seg__item rapp-seg__item--active' : 'rapp-seg__item'}
            key={key}
            onClick={() => setStatus(key)}
            role="tab"
            type="button"
          >
            {label}
            {rows ? (
              <span className={key === 'SUBMITTED' && counts[key] > 0 ? 'rapp-count rapp-count--alert' : 'rapp-count'}>
                {counts[key]}
              </span>
            ) : null}
          </button>
        ))}
      </div>
      <DataToolbar
        filters={
          <select
            aria-label="City"
            className="page-search page-search--select"
            onChange={(event) => setCity(event.target.value)}
            value={city}
          >
            <option value="">All cities</option>
            {cities.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        }
        onSearchChange={setQuery}
        searchLabel="Search applications"
        searchPlaceholder="Search by name or phone"
        searchValue={query}
      />
      <ResponsiveTable
        columns={columns}
        emptyDescription={filteredOut ? 'Try a different name, phone or city.' : EMPTY[status].description}
        emptyTitle={filteredOut ? 'No applications match' : EMPTY[status].title}
        error={error}
        errorTitle="We couldn't load applications"
        keyExtractor={(row) => row.rider_user_id}
        loading={rows === null && !error}
        mobileStatus={(row) => <ApplicationPill status={row.status} />}
        mobileSubtitle={(row) => row.phone_number ?? ''}
        mobileTitle={(row) => row.full_name || 'No name yet'}
        onRetry={load}
        onRowClick={open}
        rows={filtered}
      />
    </section>
  );
}

/**
 * The status pill with this screen's own words and tones. `StatusPill` picks a
 * tone by matching text, and "Submitted" there means a payout account sitting
 * comfortably in review - not a person waiting on us.
 */
export function ApplicationPill({ status }: { status: ApplicationStatus }) {
  const meta = STATUS_META[status];
  return <span className={`status-pill status-pill--${meta.tone}`}>{meta.label}</span>;
}
