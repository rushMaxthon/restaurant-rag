/**
 * One rider's application, checked item by item.
 *
 * Every item is accepted or flagged on its own, and the decision at the
 * bottom follows from those: approve once everything is accepted, send back
 * once something is flagged. The rules are in `services/riderApplications.ts`
 * and the server re-checks all of them under a row lock, so two admins on the
 * same application get one decision and a `state_changed` - which this page
 * answers by reloading, not by retrying.
 *
 * Photos arrive as signed links that last five minutes. The page renews them
 * every four, and whenever it regains focus, because an admin who left a tab
 * open over lunch otherwise comes back to a page of broken images.
 */

import {
  ArrowLeft,
  Check,
  ExternalLink,
  FileWarning,
  ImageOff,
  Phone,
  RotateCcw,
  RotateCw,
  ShieldCheck,
  Undo2,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { EmptyPanel } from '../components/EmptyPanel';
import { Modal } from '../components/Modal';
import { ApplicationPill } from '../components/riders/ApplicationsTab';
import { useRidersChanged } from '../hooks/useRealtime';
import { ApiError, api } from '../services/api';
import {
  GROUP_TITLES,
  ITEM_LABELS,
  ITEM_STATUS_META,
  REASONS,
  ageOn,
  applicationErrorMessage,
  decisionState,
  eventLabel,
  masked,
  mergePhotos,
  photoPairs,
  reviewItems,
  waitingLabel,
} from '../services/riderApplications';
import { VEHICLE_LABEL } from '../services/riders';
import type { ApplicationItem, ItemKind, RiderApplicationDetail, ToastMessage } from '../types/app';

interface RiderApplicationPageProps {
  token: string;
  riderUserId: string;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: ToastMessage['tone']) => void;
}

/** Renewed a minute before the server's five-minute signed links run out. */
const PHOTO_REFRESH_MS = 4 * 60_000;
/** Live hints include every rider's location ping; one refetch per this long is plenty. */
const HINT_GAP_MS = 5_000;

type Busy = `item:${ItemKind}` | 'approve' | 'send-back' | 'reject' | 'reopen' | null;

const dateTime = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
const dateOnly = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'medium' });

export function RiderApplicationPage({ token, riderUserId, onNavigate, onToast }: RiderApplicationPageProps) {
  const [detail, setDetail] = useState<RiderApplicationDetail | null>(null);
  const [loadError, setLoadError] = useState<{ status: number; message: string } | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [flagging, setFlagging] = useState<ItemKind | null>(null);
  const [zoom, setZoom] = useState<ItemKind | null>(null);
  const [rejecting, setRejecting] = useState(false);
  // Approve, send back and reopen each change what the rider sees on their
  // phone: asked once more, so a misclick on the decision bar decides nothing.
  const [asking, setAsking] = useState<'approve' | 'send-back' | 'reopen' | null>(null);
  const lastFetch = useRef(0);
  const hintTimer = useRef<number | null>(null);

  /** `fresh` renews the signed photo links; a live hint keeps the ones it has. */
  const load = useCallback(
    (fresh: boolean) => {
      lastFetch.current = Date.now();
      return api
        .getRiderApplication(token, riderUserId)
        .then((next) => {
          setDetail((previous) =>
            previous ? { ...next, photos: mergePhotos(previous.photos, next.photos, !fresh) } : next,
          );
          setLoadError(null);
        })
        .catch((e: unknown) =>
          setLoadError(
            e instanceof ApiError ? { status: e.status, message: e.message } : { status: 0, message: 'Please try again.' },
          ),
        );
    },
    [token, riderUserId],
  );

  useEffect(() => {
    void load(true);
    const id = window.setInterval(() => void load(true), PHOTO_REFRESH_MS);
    const onFocus = () => {
      if (document.visibilityState === 'visible') void load(true);
    };
    window.addEventListener('focus', onFocus);
    document.addEventListener('visibilitychange', onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener('focus', onFocus);
      document.removeEventListener('visibilitychange', onFocus);
      if (hintTimer.current !== null) window.clearTimeout(hintTimer.current);
    };
  }, [load]);

  // A resubmission or another admin's decision arrives as `riders_changed`,
  // which also carries every rider's location ping - so hints are spaced out,
  // with one trailing fetch so the last change is never missed.
  useRidersChanged(() => {
    if (hintTimer.current !== null) return;
    const wait = Math.max(0, lastFetch.current + HINT_GAP_MS - Date.now());
    hintTimer.current = window.setTimeout(() => {
      hintTimer.current = null;
      void load(false);
    }, wait);
  });

  /** Every action answers with the whole application, so the page is redrawn from it. */
  async function act(kind: Busy, run: () => Promise<RiderApplicationDetail>, success?: [string, string]) {
    setBusy(kind);
    try {
      const next = await run();
      setDetail((previous) => (previous ? { ...next, photos: mergePhotos(previous.photos, next.photos) } : next));
      if (success) onToast(success[0], success[1], 'success');
      return true;
    } catch (e: unknown) {
      const message = e instanceof ApiError ? e.message : 'Please try again.';
      if (e instanceof ApiError && e.status === 409 && message === 'state_changed') {
        onToast('Application changed', applicationErrorMessage(message), 'info');
        await load(true);
      } else {
        onToast('That did not go through', applicationErrorMessage(message), 'error');
      }
      return false;
    } finally {
      setBusy(null);
    }
  }

  const back = () => onNavigate('/riders?tab=applications');

  if (!detail) {
    return (
      <div className="page-stack rapp">
        <BackButton onClick={back} />
        <section className="admin-surface">
          {loadError ? (
            <EmptyPanel
              action={
                loadError.status === 404 ? undefined : (
                  <button className="secondary-button" onClick={() => void load(true)} type="button">
                    Try again
                  </button>
                )
              }
              description={loadError.status === 404 ? 'It may have been removed, or the link is wrong.' : loadError.message}
              title={loadError.status === 404 ? 'Application not found' : "We couldn't load this application"}
            />
          ) : (
            <p className="hint-text">Loading application…</p>
          )}
        </section>
      </div>
    );
  }

  const name = detail.sections.personal.full_name || 'The rider';
  const flaggedCount = detail.items.filter((i) => i.required && i.status === 'NEEDS_CHANGE').length;

  return (
    <ApplicationView
      busy={busy}
      detail={detail}
      onAccept={(kind) =>
        void act(`item:${kind}`, () => api.acceptApplicationItem(token, riderUserId, kind))
      }
      onApprove={() => setAsking('approve')}
      onBack={back}
      onFlag={setFlagging}
      onReject={() => setRejecting(true)}
      onReopen={() => setAsking('reopen')}
      onSendBack={() => setAsking('send-back')}
      onZoom={setZoom}
    >
      {flagging ? (
        <FlagDialog
          busy={busy === `item:${flagging}`}
          kind={flagging}
          onCancel={() => setFlagging(null)}
          onSave={async (reason) => {
            const done = await act(`item:${flagging}`, () =>
              api.flagApplicationItem(token, riderUserId, flagging, reason),
            );
            if (done) setFlagging(null);
          }}
        />
      ) : null}

      {zoom && detail.photos[zoom] ? (
        <ZoomDialog
          busy={busy === `item:${zoom}`}
          canReview={decisionState(detail).canReview}
          item={detail.items.find((item) => item.kind === zoom)}
          kind={zoom}
          onAccept={() => void act(`item:${zoom}`, () => api.acceptApplicationItem(token, riderUserId, zoom))}
          onClose={() => setZoom(null)}
          onFlag={() => {
            // Closed first: two dialogs share a layer, and the reason picker
            // would open underneath the photo.
            setZoom(null);
            setFlagging(zoom);
          }}
          url={detail.photos[zoom] as string}
        />
      ) : null}

      <ConfirmDialog
        busy={busy === asking}
        confirmLabel={asking === 'approve' ? 'Approve rider' : asking === 'send-back' ? 'Send back' : 'Reopen'}
        description={
          asking === 'approve'
            ? `${name} will be able to go online and take orders straight away.`
            : asking === 'send-back'
              ? `${name} will be asked to fix ${flaggedCount} ${flaggedCount === 1 ? 'item' : 'items'}, with your reasons.`
              : `${name} will be able to fix and resubmit the application, and it comes back to this queue.`
        }
        eyebrow="Rider application"
        onCancel={() => setAsking(null)}
        onConfirm={async () => {
          const which = asking;
          const done =
            which === 'approve'
              ? await act('approve', () => api.approveApplication(token, riderUserId), [
                  'Rider approved',
                  `${name} can now go online and take orders.`,
                ])
              : which === 'send-back'
                ? await act('send-back', () => api.sendBackApplication(token, riderUserId), [
                    'Sent back for changes',
                    'The rider has been told what to fix.',
                  ])
                : await act('reopen', () => api.reopenApplication(token, riderUserId), [
                    'Application reopened',
                    'The rider can resubmit it, and it comes back to this queue.',
                  ]);
          if (done) setAsking(null);
        }}
        open={asking !== null}
        title={
          asking === 'approve'
            ? `Approve ${name}?`
            : asking === 'send-back'
              ? 'Send back for changes?'
              : 'Reopen this application?'
        }
      />
      {rejecting ? (
        <RejectDialog
          busy={busy === 'reject'}
          name={detail.sections.personal.full_name}
          onCancel={() => setRejecting(false)}
          onConfirm={async (reason) => {
            const done = await act('reject', () => api.rejectApplication(token, riderUserId, reason), [
              'Application rejected',
              'The rider has been told. You can reopen it later if this was a mistake.',
            ]);
            if (done) setRejecting(false);
          }}
        />
      ) : null}
    </ApplicationView>
  );
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button className="secondary-button rapp-back" onClick={onClick} type="button">
      <ArrowLeft size={16} strokeWidth={2.1} />
      <span>Applications</span>
    </button>
  );
}

// --- the page body -----------------------------------------------------------------

interface ViewProps {
  detail: RiderApplicationDetail;
  busy: Busy;
  onBack: () => void;
  onAccept: (kind: ItemKind) => void;
  onFlag: (kind: ItemKind) => void;
  onZoom: (kind: ItemKind) => void;
  onApprove: () => void;
  onSendBack: () => void;
  onReject: () => void;
  onReopen: () => void;
  children: ReactNode;
}

function ApplicationView({
  detail,
  busy,
  onBack,
  onAccept,
  onFlag,
  onZoom,
  onApprove,
  onSendBack,
  onReject,
  onReopen,
  children,
}: ViewProps) {
  const { personal, vehicle, documents, bank } = detail.sections;
  const decision = decisionState(detail);
  const items = useMemo(() => reviewItems(detail.items), [detail.items]);
  const itemOf = (kind: ItemKind) => items.find((item) => item.kind === kind);
  const groups = useMemo(() => photoPairs(detail.items), [detail.items]);
  const accepted = items.filter((item) => item.status === 'ACCEPTED').length;
  const flagged = items.filter((item) => item.status === 'NEEDS_CHANGE').length;
  const age = ageOn(personal.date_of_birth);
  const name = personal.full_name || 'No name yet';
  const selfie = detail.photos.SELFIE;
  const phoneDigits = (detail.phone_number ?? '').replace(/[^\d+]/g, '');

  const review = { canReview: decision.canReview, busy, onAccept, onFlag };

  return (
    <div className="page-stack rapp">
      <BackButton onClick={onBack} />

      <header className="rapp-head">
        <div className="rapp-head__who">
          {selfie ? (
            <img alt="" className="rapp-avatar" src={selfie} />
          ) : (
            <span aria-hidden className="rapp-avatar rapp-avatar--initials">
              {initials(name)}
            </span>
          )}
          <div className="rapp-head__copy">
            <span className="eyebrow">Rider application</span>
            <h1>{name}</h1>
            <div className="rapp-head__meta">
              {detail.phone_number ? (
                <a className="rapp-tel" href={`tel:${phoneDigits}`}>
                  <Phone size={14} strokeWidth={2.2} />
                  {detail.phone_number}
                </a>
              ) : null}
              {personal.city ? <span>{personal.city}</span> : null}
              {vehicle.vehicle_type ? <span>{VEHICLE_LABEL[vehicle.vehicle_type]}</span> : null}
              {detail.submitted_at ? (
                <span>
                  Submitted {dateTime(detail.submitted_at)}
                  {detail.status === 'SUBMITTED' ? ` · waiting ${waitingLabel(detail.submitted_at).toLowerCase()}` : ''}
                </span>
              ) : (
                <span>Not submitted yet</span>
              )}
            </div>
          </div>
        </div>
        <ApplicationPill status={detail.status} />
      </header>

      {detail.status === 'REJECTED' && detail.final_reason ? (
        <Notice tone="danger" title="Rejected">
          {detail.final_reason}
          {detail.decided_at ? ` · ${dateTime(detail.decided_at)}` : ''}
        </Notice>
      ) : null}
      {detail.status === 'CHANGES_NEEDED' ? (
        <Notice tone="info" title="With the rider">
          Sent back{detail.decided_at ? ` on ${dateTime(detail.decided_at)}` : ''}. It returns to the queue when they
          resubmit.
        </Notice>
      ) : null}
      {detail.missing.length > 0 && detail.status !== 'DRAFT' ? (
        <Notice tone="warning" title="Incomplete">
          Missing: {detail.missing.map((kind) => ITEM_LABELS[kind]).join(', ')}.
        </Notice>
      ) : null}
      {detail.photos_error ? (
        <Notice tone="warning" title="Photos unavailable">
          {detail.photos_error === 'storage_not_configured'
            ? "Document photos can't be shown: storage isn't configured (SUPABASE_URL / SUPABASE_SERVICE_KEY)."
            : `Document photos can't be shown right now (${detail.photos_error}).`}
        </Notice>
      ) : null}

      <div className="rapp-grid">
        <div className="rapp-col">
          <SectionCard item={itemOf('PERSONAL')} review={review} title="Personal details">
            <Facts
              rows={[
                ['Full name', personal.full_name],
                [
                  'Date of birth',
                  personal.date_of_birth ? `${dateOnly(personal.date_of_birth)}${age !== null ? ` · ${age} years` : ''}` : '',
                ],
                ['City', personal.city],
                ['Address', [personal.address_line, personal.pincode].filter(Boolean).join(', ')],
                [
                  'Emergency contact',
                  personal.emergency_name || personal.emergency_phone ? (
                    <>
                      {personal.emergency_name}
                      {personal.emergency_phone ? (
                        <>
                          {' · '}
                          <a href={`tel:${personal.emergency_phone}`}>{personal.emergency_phone}</a>
                        </>
                      ) : null}
                    </>
                  ) : (
                    ''
                  ),
                ],
              ]}
            />
          </SectionCard>

          <SectionCard item={itemOf('VEHICLE_DETAILS')} review={review} title="Vehicle">
            <Facts
              rows={[
                ['Type', vehicle.vehicle_type ? VEHICLE_LABEL[vehicle.vehicle_type] : ''],
                ['Number plate', vehicle.vehicle_number ? <span className="rapp-mono">{vehicle.vehicle_number}</span> : ''],
              ]}
            />
            {!itemOf('VEHICLE_DETAILS') && vehicle.vehicle_type ? (
              <p className="hint-text">No registration or licence is needed for this vehicle.</p>
            ) : null}
          </SectionCard>

          <SectionCard item={itemOf('BANK_DETAILS')} review={review} title="Bank">
            <Facts
              rows={[
                ['Account holder', bank.bank_holder],
                ['Account number', bank.bank_account_last4 ? <span className="rapp-mono">{masked(bank.bank_account_last4)}</span> : ''],
                ['IFSC', bank.ifsc ? <span className="rapp-mono">{bank.ifsc}</span> : ''],
                ['UPI ID', bank.upi_id],
              ]}
            />
          </SectionCard>

          <History detail={detail} />
        </div>

        <div className="rapp-col">
          <div className="rapp-col__head">
            <h2>Documents</h2>
            <span className="hint-text">
              {accepted} of {items.length} items accepted{flagged ? ` · ${flagged} flagged` : ''}
            </span>
          </div>
          {groups.length === 0 ? (
            <section className="rapp-card">
              <p className="hint-text">No documents uploaded yet.</p>
            </section>
          ) : (
            groups.map((group) => (
              <DocumentCard
                detail={detail}
                documents={documents}
                group={group}
                key={group[0].kind}
                onZoom={onZoom}
                review={review}
              />
            ))
          )}
        </div>
      </div>

      <DecisionBar
        accepted={accepted}
        busy={busy}
        decision={decision}
        detail={detail}
        flagged={flagged}
        onApprove={onApprove}
        onReject={onReject}
        onReopen={onReopen}
        onSendBack={onSendBack}
        total={items.length}
      />
      {children}
    </div>
  );
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? '?') + (parts.length > 1 ? parts[parts.length - 1][0] : '')).toUpperCase();
}

function Notice({ tone, title, children }: { tone: 'danger' | 'info' | 'warning'; title: string; children: ReactNode }) {
  return (
    <div className={`rapp-notice rapp-notice--${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>
      <FileWarning aria-hidden size={18} strokeWidth={2.1} />
      <p>
        <strong>{title}.</strong> {children}
      </p>
    </div>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="rapp-facts">
      {rows.map(([label, value]) => (
        <div className="rapp-facts__row" key={label}>
          <dt>{label}</dt>
          <dd>{value || <span className="hint-text">Not given</span>}</dd>
        </div>
      ))}
    </dl>
  );
}

// --- review controls ---------------------------------------------------------------

interface ReviewProps {
  canReview: boolean;
  busy: Busy;
  onAccept: (kind: ItemKind) => void;
  onFlag: (kind: ItemKind) => void;
}

function ItemPill({ item }: { item: ApplicationItem }) {
  const meta = ITEM_STATUS_META[item.status];
  return <span className={`status-pill status-pill--${meta.tone}`}>{meta.label}</span>;
}

/** The admin's reason, shown where the rider will be asked to fix it. */
function FlagReason({ item }: { item: ApplicationItem }) {
  if (item.status !== 'NEEDS_CHANGE' || !item.reason) return null;
  return <p className="rapp-reason">{item.reason}</p>;
}

/**
 * Accept and Needs change, only while the application is SUBMITTED - the
 * server refuses item review in any other state, so offering it would be a
 * button that always fails.
 */
function ItemActions({ item, review }: { item: ApplicationItem; review: ReviewProps }) {
  if (!review.canReview) return null;
  const working = review.busy === `item:${item.kind}`;
  const label = ITEM_LABELS[item.kind];
  return (
    <div className="rapp-actions">
      <button
        aria-label={`Accept ${label}`}
        aria-pressed={item.status === 'ACCEPTED'}
        className={item.status === 'ACCEPTED' ? 'rapp-btn rapp-btn--accepted' : 'rapp-btn rapp-btn--accept'}
        disabled={working || item.status === 'ACCEPTED' || item.status === 'MISSING'}
        onClick={() => review.onAccept(item.kind)}
        type="button"
      >
        <Check size={15} strokeWidth={2.4} />
        {item.status === 'ACCEPTED' ? 'Accepted' : 'Accept'}
      </button>
      <button
        aria-label={`${label} needs a change`}
        className={item.status === 'NEEDS_CHANGE' ? 'rapp-btn rapp-btn--flagged' : 'rapp-btn rapp-btn--flag'}
        disabled={working}
        onClick={() => review.onFlag(item.kind)}
        type="button"
      >
        <X size={15} strokeWidth={2.4} />
        {item.status === 'NEEDS_CHANGE' ? 'Change reason' : 'Needs change'}
      </button>
    </div>
  );
}

function SectionCard({
  title,
  item,
  review,
  children,
}: {
  title: string;
  item: ApplicationItem | undefined;
  review: ReviewProps;
  children: ReactNode;
}) {
  return (
    <section className={`rapp-card${item?.status === 'NEEDS_CHANGE' ? ' rapp-card--flagged' : ''}`}>
      <div className="rapp-card__head">
        <h2>{title}</h2>
        {item ? <ItemPill item={item} /> : null}
      </div>
      {children}
      {item ? <FlagReason item={item} /> : null}
      {item ? <ItemActions item={item} review={review} /> : null}
    </section>
  );
}

/** The number typed for each document, beside its photo, so the two can be compared. */
function documentLine(kind: ItemKind, documents: RiderApplicationDetail['sections']['documents']): ReactNode {
  if (kind === 'AADHAAR_FRONT') return documents.aadhaar_last4 ? `Number ${masked(documents.aadhaar_last4)}` : null;
  if (kind === 'PAN') return documents.pan_last4 ? `Number ${masked(documents.pan_last4)}` : null;
  if (kind === 'LICENCE_FRONT') {
    const expiry = documents.licence_expiry;
    const expired = expiry ? new Date(`${expiry}T23:59:59`) < new Date() : false;
    return (
      <>
        {documents.licence_last4 ? `Number ${masked(documents.licence_last4)}` : null}
        {expiry ? (
          <span className={expired ? 'rapp-expired' : undefined}>
            {documents.licence_last4 ? ' · ' : ''}
            {expired ? 'Expired ' : 'Valid till '}
            {dateOnly(expiry)}
          </span>
        ) : null}
      </>
    );
  }
  return null;
}

function DocumentCard({
  group,
  detail,
  documents,
  review,
  onZoom,
}: {
  group: ApplicationItem[];
  detail: RiderApplicationDetail;
  documents: RiderApplicationDetail['sections']['documents'];
  review: ReviewProps;
  onZoom: (kind: ItemKind) => void;
}) {
  const paired = group.length > 1;
  const line = documentLine(group[0].kind, documents);
  const anyFlagged = group.some((item) => item.status === 'NEEDS_CHANGE');
  return (
    <section className={`rapp-card${anyFlagged ? ' rapp-card--flagged' : ''}`}>
      <div className="rapp-card__head">
        <div>
          <h2>{GROUP_TITLES[group[0].kind] ?? ITEM_LABELS[group[0].kind]}</h2>
          {line ? <p className="rapp-card__sub">{line}</p> : null}
        </div>
        {paired ? null : <ItemPill item={group[0]} />}
      </div>
      <div className={paired ? 'rapp-sides rapp-sides--pair' : 'rapp-sides'}>
        {group.map((item) => (
          <div className="rapp-side" key={item.kind}>
            <Photo
              item={item}
              label={ITEM_LABELS[item.kind]}
              onZoom={() => onZoom(item.kind)}
              missing={(detail.missing_photos ?? []).includes(item.kind)}
              unavailable={Boolean(detail.photos_error)}
              url={detail.photos[item.kind]}
            />
            {paired ? (
              <div className="rapp-side__caption">
                <span>{item.kind.endsWith('_BACK') ? 'Back' : 'Front'}</span>
                <ItemPill item={item} />
              </div>
            ) : null}
            <FlagReason item={item} />
            <ItemActions item={item} review={review} />
          </div>
        ))}
      </div>
    </section>
  );
}

function Photo({
  item,
  url,
  label,
  missing,
  unavailable,
  onZoom,
}: {
  item: ApplicationItem;
  url: string | undefined;
  label: string;
  /** Uploaded, but the file is gone from storage: only this photo is lost. */
  missing: boolean;
  unavailable: boolean;
  onZoom: () => void;
}) {
  const [broken, setBroken] = useState<string | null>(null);
  if (url && broken !== url) {
    return (
      <button aria-label={`Zoom into ${label}`} className="rapp-photo" onClick={onZoom} type="button">
        <img alt={label} loading="lazy" onError={() => setBroken(url)} src={url} />
      </button>
    );
  }
  const text = !item.has_photo
    ? 'Not uploaded'
    : missing
      ? 'File missing - mark "Needs change" so the rider uploads it again'
      : unavailable
      ? "Can't be shown"
      : broken
        ? 'The link expired - it renews within a few minutes'
        : 'Photo unavailable';
  return (
    <div className="rapp-photo rapp-photo--empty">
      <ImageOff aria-hidden size={22} strokeWidth={1.8} />
      <span>{text}</span>
    </div>
  );
}

function History({ detail }: { detail: RiderApplicationDetail }) {
  const events = [...detail.events].sort((a, b) => b.at.localeCompare(a.at));
  return (
    <section className="rapp-card">
      <div className="rapp-card__head">
        <h2>History</h2>
      </div>
      {events.length === 0 ? (
        <p className="hint-text">Nothing has happened yet.</p>
      ) : (
        <ol className="rapp-history">
          {events.map((event, index) => (
            <li className={`rapp-history__item rapp-history__item--${event.action.toLowerCase()}`} key={`${event.at}-${index}`}>
              <strong>{eventLabel(event)}</strong>
              {event.note ? <span className="rapp-history__note">{event.note}</span> : null}
              <span className="rapp-history__meta">
                {event.actor_name ? `${event.actor_name} · ` : ''}
                {dateTime(event.at)}
              </span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

// --- the decision ------------------------------------------------------------------

function DecisionBar({
  detail,
  decision,
  busy,
  accepted,
  flagged,
  total,
  onApprove,
  onSendBack,
  onReject,
  onReopen,
}: {
  detail: RiderApplicationDetail;
  decision: ReturnType<typeof decisionState>;
  busy: Busy;
  accepted: number;
  flagged: number;
  total: number;
  onApprove: () => void;
  onSendBack: () => void;
  onReject: () => void;
  onReopen: () => void;
}) {
  const working = busy !== null;
  const summary =
    detail.status === 'SUBMITTED'
      ? `${accepted} of ${total} accepted${flagged ? ` · ${flagged} flagged` : ''}`
      : detail.status === 'APPROVED' && detail.decided_at
        ? `Approved ${dateTime(detail.decided_at)}`
        : decision.approveReason;

  return (
    <div aria-label="Decision" className="rapp-bar" role="region">
      <p className="rapp-bar__summary">{summary}</p>
      <div className="rapp-bar__actions">
        {decision.canReject ? (
          <button className="secondary-button rapp-bar__danger" disabled={working} onClick={onReject} type="button">
            Reject permanently
          </button>
        ) : null}
        {decision.canReopen ? (
          <button className="secondary-button" disabled={working} onClick={onReopen} type="button">
            <Undo2 size={15} strokeWidth={2.2} />
            {busy === 'reopen' ? 'Reopening…' : 'Reopen'}
          </button>
        ) : null}
        {detail.status === 'SUBMITTED' ? (
          <>
            <div className="rapp-bar__action">
              <button className="secondary-button" disabled={working || !decision.canSendBack} onClick={onSendBack} type="button">
                {busy === 'send-back' ? 'Sending…' : 'Send back for changes'}
              </button>
              {decision.sendBackReason ? <small>{decision.sendBackReason}</small> : null}
            </div>
            <div className="rapp-bar__action">
              <button className="primary-button" disabled={working || !decision.canApprove} onClick={onApprove} type="button">
                <ShieldCheck size={16} strokeWidth={2.2} />
                {busy === 'approve' ? 'Approving…' : 'Approve rider'}
              </button>
              {decision.approveReason ? <small>{decision.approveReason}</small> : null}
            </div>
          </>
        ) : null}
      </div>
    </div>
  );
}

// --- dialogs -------------------------------------------------------------------------

function FlagDialog({
  kind,
  busy,
  onCancel,
  onSave,
}: {
  kind: ItemKind;
  busy: boolean;
  onCancel: () => void;
  onSave: (reason: string) => void;
}) {
  const [reason, setReason] = useState('');
  const trimmed = reason.trim();
  return (
    <Modal busy={busy} className="modal-card--compact" labelledBy="rapp-flag-title" onClose={onCancel}>
      <div className="panel__header modal-card__header">
        <div>
          <span className="eyebrow">{ITEM_LABELS[kind]}</span>
          <h2 id="rapp-flag-title">What needs changing?</h2>
          <p className="hint-text">The rider sees this reason exactly as written, beside a Fix button.</p>
        </div>
        <button aria-label="Close" className="modal-close" onClick={onCancel} type="button">
          ×
        </button>
      </div>
      <div className="modal-card__body rapp-flag">
        <div className="rapp-chips" role="group" aria-label="Common reasons">
          {REASONS.map((text) => (
            <button
              aria-pressed={trimmed === text}
              className={trimmed === text ? 'rapp-chip rapp-chip--on' : 'rapp-chip'}
              key={text}
              onClick={() => setReason(text)}
              type="button"
            >
              {text}
            </button>
          ))}
        </div>
        <label className="field">
          <span>Reason</span>
          <textarea
            maxLength={300}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Pick one above or describe the problem"
            rows={3}
            value={reason}
          />
          {!trimmed ? <small>A reason is required, so the rider knows what to fix.</small> : null}
        </label>
        <div className="modal-actions">
          <button className="secondary-button" disabled={busy} onClick={onCancel} type="button">
            Cancel
          </button>
          <button
            className="primary-button primary-button--danger"
            disabled={busy || !trimmed}
            onClick={() => onSave(trimmed)}
            type="button"
          >
            {busy ? 'Saving…' : 'Mark needs change'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function ZoomDialog({
  kind,
  url,
  item,
  canReview,
  busy,
  onClose,
  onAccept,
  onFlag,
}: {
  kind: ItemKind;
  url: string;
  item: ApplicationItem | undefined;
  canReview: boolean;
  busy: boolean;
  onClose: () => void;
  onAccept: () => void;
  onFlag: () => void;
}) {
  // Phones photograph documents sideways more often than not; a quarter turn
  // in CSS is enough to read one, and nothing is changed on the server.
  const [turns, setTurns] = useState(0);
  const sideways = Math.abs(turns % 2) === 1;
  return (
    <Modal className="rapp-zoom" labelledBy="rapp-zoom-title" onClose={onClose}>
      <div className="panel__header modal-card__header">
        <div className="rapp-zoom__title">
          <h2 id="rapp-zoom-title">{ITEM_LABELS[kind]}</h2>
          {item ? <ItemPill item={item} /> : null}
        </div>
        <button aria-label="Close" className="modal-close" onClick={onClose} type="button">
          ×
        </button>
      </div>
      <div className="rapp-zoom__stage">
        <img
          alt={ITEM_LABELS[kind]}
          className={sideways ? 'rapp-zoom__img rapp-zoom__img--sideways' : 'rapp-zoom__img'}
          src={url}
          style={{ transform: `rotate(${turns * 90}deg)` }}
        />
      </div>
      <div className="rapp-zoom__tools">
        <div className="rapp-actions">
          <button className="secondary-button" onClick={() => setTurns((t) => t - 1)} type="button">
            <RotateCcw size={15} strokeWidth={2.2} />
            Rotate left
          </button>
          <button className="secondary-button" onClick={() => setTurns((t) => t + 1)} type="button">
            <RotateCw size={15} strokeWidth={2.2} />
            Rotate right
          </button>
          <a className="secondary-button" href={url} rel="noreferrer" target="_blank">
            <ExternalLink size={15} strokeWidth={2.2} />
            Open full size
          </a>
        </div>
        {canReview && item ? (
          <div className="rapp-actions">
            <button className="secondary-button" disabled={busy} onClick={onFlag} type="button">
              <X size={15} strokeWidth={2.4} />
              Needs change
            </button>
            <button
              className="primary-button"
              disabled={busy || item.status === 'ACCEPTED'}
              onClick={onAccept}
              type="button"
            >
              <Check size={15} strokeWidth={2.4} />
              {item.status === 'ACCEPTED' ? 'Accepted' : 'Accept'}
            </button>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

function RejectDialog({
  name,
  busy,
  onCancel,
  onConfirm,
}: {
  name: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState('');
  const trimmed = reason.trim();
  return (
    <ConfirmDialog
      busy={busy}
      confirmDisabled={!trimmed}
      confirmLabel="Reject permanently"
      description={`${name || 'This rider'} will be told the application was not approved and cannot resubmit it. You can reopen it later if this was a mistake.`}
      eyebrow="Reject application"
      onCancel={onCancel}
      onConfirm={() => onConfirm(trimmed)}
      open
      title="Reject this rider?"
      tone="danger"
    >
      <label className="field rapp-reject">
        <span>Reason (the rider sees this)</span>
        <textarea
          autoFocus
          maxLength={500}
          onChange={(event) => setReason(event.target.value)}
          placeholder="e.g. Documents belong to someone else"
          rows={3}
          value={reason}
        />
        {!trimmed ? <small>A reason is required.</small> : null}
      </label>
    </ConfirmDialog>
  );
}
