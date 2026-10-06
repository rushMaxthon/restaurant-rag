/**
 * The printers a branch's tickets come out of.
 *
 * Until this screen existed the only way to set one up was a curl call, which
 * is not a thing a restaurant can be asked to do. Everything here is already
 * enforced by the backend — `resolve_insights_scope` decides which restaurant
 * a caller may touch, the `transport_is_exhaustive` CHECK decides whether a
 * printer row is well-formed, and the API refuses two printers on one
 * address. This page picks; the server refuses.
 *
 * Two things it is designed to answer, because they are the two questions
 * anybody actually arrives with:
 *
 * **"Is it working?"** An agent is online, offline, or has never connected —
 * and the third is a different fact from the second: it was paired and never
 * started, which is a mistake somebody can fix.
 *
 * **"Why did nothing print?"** The jobs list carries `last_error`, a sentence
 * written for an owner rather than an exception. That string is the whole
 * reason the backend phrases printer failures as advice.
 *
 * There is no delete, for the same reason `KitchenStaffPage` has none:
 * `print_jobs` points at these rows, and removing an agent would take the
 * record of what it printed with it. An agent that should stop is switched
 * off, which the backend answers by bumping `token_version` so the PC stops
 * on its next poll.
 */

import {
  Copy,
  MonitorSmartphone,
  Plus,
  Power,
  Printer as PrinterIcon,
  RefreshCw,
  Store,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { Modal } from '../components/Modal';
import { PageIntro } from '../components/PageIntro';
import { ResponsiveTable, type TableColumn } from '../components/ResponsiveTable';
import { StatePanel } from '../components/StatePanel';
import { StatusPill } from '../components/StatusPill';
import { RestaurantScopePicker } from '../components/marketing/RestaurantScopePicker';
import { useMarketingScope } from '../hooks/useMarketingScope';
import { ApiError, api, formatDate } from '../services/api';
import {
  DOCKET_KINDS,
  EMPTY_PRINTER_FORM,
  PAPER_WIDTHS,
  agentLiveness,
  buildPrinterPayload,
  hasErrors,
  printerAddress,
  sinceLabel,
  validatePrinterForm,
  type PrinterFormErrors,
} from '../services/printing';
import type { PrintAgent, PrintJob, Printer, PrinterForm } from '../types/printing';
import type { RestaurantLocation, UserRole } from '../types/app';

interface PrintersPageProps {
  token: string;
  role: UserRole;
  /** The owner's own restaurant. Null for an admin, who chooses one. */
  restaurantId: string | null;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

export function PrintersPage({ token, role, restaurantId, onToast }: PrintersPageProps) {
  const scope = useMarketingScope();
  const isAdmin = role === 'ADMIN';
  // An owner passes null and the backend resolves their restaurant; an admin
  // must name one. Getting this backwards is a 400 or a 403, not a degraded
  // screen — see CLAUDE.md.
  const scopedRestaurantId = isAdmin ? scope.selectedRestaurantId : null;
  const ownRestaurantId = isAdmin ? scope.selectedRestaurantId : restaurantId;

  const [agents, setAgents] = useState<PrintAgent[]>([]);
  const [jobs, setJobs] = useState<PrintJob[]>([]);
  const [locations, setLocations] = useState<RestaurantLocation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [pairing, setPairing] = useState<{ code: string; expiresAt: string; branch: string } | null>(
    null,
  );
  const [pairOpen, setPairOpen] = useState(false);
  const [pairBranch, setPairBranch] = useState('');
  const [pairName, setPairName] = useState('Kitchen PC');

  const [printerModal, setPrinterModal] = useState<{
    agentId: string;
    printer: Printer | null;
  } | null>(null);
  const [form, setForm] = useState<PrinterForm>(EMPTY_PRINTER_FORM);
  const [formErrors, setFormErrors] = useState<PrinterFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState<PrintAgent | null>(null);

  const load = useCallback(
    async (quiet = false) => {
      if (isAdmin && !scope.ready) {
        // Fetching before a restaurant is chosen is exactly what turns "pick
        // a restaurant" into "it didn't load".
        setLoading(false);
        return;
      }
      if (!quiet) setLoading(true);
      setError(null);
      try {
        const [agentRows, jobRows] = await Promise.all([
          api.getPrintAgents(token, scopedRestaurantId),
          api.getPrintJobs(token, scopedRestaurantId, 30),
        ]);
        setAgents(agentRows);
        setJobs(jobRows);
      } catch (caught) {
        setError(caught instanceof ApiError ? caught.message : 'Could not load printers.');
      } finally {
        setLoading(false);
      }
    },
    [isAdmin, scope.ready, scopedRestaurantId, token],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // The branches, for the pairing dialog. A printer belongs to exactly one,
  // because it is a physical object in one room.
  useEffect(() => {
    if (!ownRestaurantId) return;
    let cancelled = false;
    api
      .getRestaurant(token, ownRestaurantId)
      .then((restaurant) => {
        if (cancelled) return;
        const rows = restaurant.locations ?? [];
        setLocations(rows);
        setPairBranch((current) => current || rows[0]?.id || '');
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [ownRestaurantId, token]);

  // Refreshed while the screen is open, because this is the page somebody
  // watches during a setup: they press Test print, walk to the printer, and
  // come back expecting the status to have changed.
  useEffect(() => {
    const timer = window.setInterval(() => void load(true), 10_000);
    return () => window.clearInterval(timer);
  }, [load]);

  async function createCode() {
    if (!pairBranch) {
      onToast('Choose a branch', 'A printer belongs to one branch.', 'error');
      return;
    }
    try {
      const reply = await api.createPairingCode(token, {
        restaurant_location_id: pairBranch,
        name: pairName.trim() || 'Kitchen PC',
        restaurant_id: scopedRestaurantId,
      });
      setPairing({ code: reply.code, expiresAt: reply.expires_at, branch: reply.branch_name });
    } catch (caught) {
      onToast(
        'Could not create a code',
        caught instanceof ApiError ? caught.message : 'Please try again.',
        'error',
      );
    }
  }

  function openPrinter(agentId: string, printer: Printer | null) {
    setPrinterModal({ agentId, printer });
    setFormErrors({});
    setForm(
      printer
        ? {
            name: printer.name,
            transport: printer.transport,
            host: printer.host ?? '',
            port: String(printer.port ?? 9100),
            windows_printer_name: printer.windows_printer_name ?? '',
            paper_width_chars: printer.paper_width_chars,
            copies: String(printer.copies),
            docket_kinds: printer.docket_kinds.filter(
              (kind): kind is (typeof DOCKET_KINDS)[number]['value'] =>
                DOCKET_KINDS.some((known) => known.value === kind),
            ),
          }
        : EMPTY_PRINTER_FORM,
    );
  }

  async function savePrinter() {
    if (!printerModal) return;
    const errors = validatePrinterForm(form);
    setFormErrors(errors);
    if (hasErrors(errors)) return;

    setSaving(true);
    try {
      const payload = buildPrinterPayload(form);
      if (printerModal.printer) {
        await api.updatePrinter(token, printerModal.printer.id, payload, scopedRestaurantId);
        onToast('Printer saved', `${payload.name} updated.`, 'success');
      } else {
        await api.addPrinter(token, printerModal.agentId, payload, scopedRestaurantId);
        onToast('Printer added', `${payload.name} is ready. Try a test print.`, 'success');
      }
      setPrinterModal(null);
      await load(true);
    } catch (caught) {
      // The duplicate-address refusal lands here, and it is a sentence worth
      // showing verbatim: two printers on one address means every ticket
      // prints twice.
      onToast(
        'Could not save',
        caught instanceof ApiError ? caught.message : 'Please try again.',
        'error',
      );
    } finally {
      setSaving(false);
    }
  }

  async function test(printer: Printer) {
    try {
      await api.testPrint(token, printer.id, scopedRestaurantId);
      onToast(
        'Test page queued',
        `It should come out of ${printer.name} within a few seconds.`,
        'success',
      );
      await load(true);
    } catch (caught) {
      onToast(
        'Could not queue the test',
        caught instanceof ApiError ? caught.message : 'Please try again.',
        'error',
      );
    }
  }

  async function toggleAgent(agent: PrintAgent) {
    try {
      await api.updatePrintAgent(
        token,
        agent.id,
        { is_enabled: !agent.is_enabled },
        scopedRestaurantId,
      );
      onToast(
        agent.is_enabled ? 'Agent switched off' : 'Agent switched on',
        agent.is_enabled
          ? 'That PC will stop printing on its next check.'
          : 'That PC will start printing again on its next check.',
        'success',
      );
      setToggling(null);
      await load(true);
    } catch (caught) {
      onToast(
        'Could not change that',
        caught instanceof ApiError ? caught.message : 'Please try again.',
        'error',
      );
    }
  }

  const jobColumns = useMemo<TableColumn<PrintJob>[]>(
    () => [
      {
        id: 'kind',
        header: 'Ticket',
        render: (job) => (
          <span>
            {job.kind.replace(/_/g, ' ').toLowerCase()}
            {job.source === 'MANUAL' ? ' (by hand)' : ''}
          </span>
        ),
      },
      { id: 'printer', header: 'Printer', render: (job) => job.printer_name ?? '—' },
      {
        id: 'status',
        header: 'Status',
        // The tone comes from `statusPillUtils`, where PRINTED, QUEUED and
        // CLAIMED were added alongside every other status this panel shows.
        // Deciding it here would be a second opinion about what green means.
        render: (job) => <StatusPill status={job.status} />,
      },
      {
        id: 'when',
        header: 'When',
        render: (job) => formatDate(job.printed_at ?? job.created_at),
      },
      {
        id: 'why',
        header: 'Notes',
        render: (job) =>
          job.last_error ? (
            <span className="print-job-error">{job.last_error}</span>
          ) : job.attempts > 1 ? (
            <span className="hint-text">{job.attempts} attempts</span>
          ) : (
            <span className="hint-text">—</span>
          ),
      },
    ],
    [],
  );

  if (isAdmin && !scope.ready) {
    return (
      <div className="page-stack">
        <PageIntro
          eyebrow="Printing"
          title="Printers"
          description="Tickets printed in the kitchen the moment an order is paid for."
        />
        <RestaurantScopePicker scope={scope} />
        <StatePanel
          icon={Store}
          title="Choose a restaurant"
          description="Printers belong to a branch, so pick the restaurant first."
        />
      </div>
    );
  }

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Printing"
        title="Printers"
        description="Tickets printed in the kitchen the moment an order is paid for. No browser needed."
        actions={
          <>
            <button className="secondary-button" onClick={() => void load()} type="button">
              <RefreshCw aria-hidden size={16} /> Refresh
            </button>
            <button
              className="primary-button"
              onClick={() => {
                setPairing(null);
                setPairOpen(true);
              }}
              type="button"
            >
              <MonitorSmartphone aria-hidden size={16} /> Connect a PC
            </button>
          </>
        }
      />

      {isAdmin && <RestaurantScopePicker scope={scope} />}

      {error && (
        <StatePanel
          icon={PrinterIcon}
          title="Could not load"
          description={error}
          action={
            <button className="secondary-button" onClick={() => void load()} type="button">
              Try again
            </button>
          }
        />
      )}

      {!error && loading && (
        <StatePanel
          description="Fetching the printers set up for this restaurant."
          icon={PrinterIcon}
          title="Loading printers…"
        />
      )}

      {!error && !loading && agents.length === 0 && (
        <StatePanel
          icon={PrinterIcon}
          title="No kitchen PC connected yet"
          description={
            'Connect the PC that sits next to the printer: press Connect a PC for a ' +
            'six-digit code, run the agent on that machine, and type the code in. ' +
            'Orders print from then on, with no browser open.'
          }
          action={
            <button className="primary-button" onClick={() => setPairOpen(true)} type="button">
              <MonitorSmartphone aria-hidden size={16} /> Connect a PC
            </button>
          }
        />
      )}

      {agents.map((agent) => {
        const liveness = agentLiveness(agent.last_seen_at);
        return (
          <section className="admin-surface print-agent" key={agent.id}>
            <header className="print-agent__head">
              <div>
                <h2>{agent.name}</h2>
                <p className="hint-text">
                  {agent.branch_name ?? 'unknown branch'}
                  {agent.hostname ? ` · ${agent.hostname}` : ''}
                  {agent.agent_version ? ` · v${agent.agent_version}` : ''}
                </p>
              </div>
              <div className="print-agent__state">
                {/* Three states, not two. "Never connected" is a different
                    and more actionable fact than "offline": it was paired
                    and the agent was never started. */}
                <StatusPill
                  status={
                    !agent.is_enabled
                      ? 'SWITCHED OFF'
                      : liveness === 'online'
                        ? 'ONLINE'
                        : liveness === 'never'
                          ? 'NEVER CONNECTED'
                          : 'OFFLINE'
                  }
                />
                <span className="hint-text">seen {sinceLabel(agent.last_seen_at)}</span>
                <button
                  className="secondary-button"
                  onClick={() => setToggling(agent)}
                  type="button"
                >
                  <Power aria-hidden size={15} />
                  {agent.is_enabled ? 'Switch off' : 'Switch on'}
                </button>
              </div>
            </header>

            {agent.printers.length === 0 ? (
              // Deliberately a call to action rather than a warning. This PC is
              // working correctly; it simply has not been told where the
              // printer is, and an amber strip above a separate button read as
              // a problem AND a chore.
              <div className="print-agent__setup">
                <strong>One step left: where is the printer?</strong>
                <p>
                  This PC is connected and waiting. Tell it the printer&rsquo;s address and
                  tickets start coming out.
                </p>
                <button
                  className="primary-button"
                  onClick={() => openPrinter(agent.id, null)}
                  type="button"
                >
                  <Plus aria-hidden size={16} /> Add the printer
                </button>
              </div>
            ) : (
              <ul className="printer-list">
                {agent.printers.map((printer) => (
                  <li className="printer-row" key={printer.id}>
                    <div className="printer-row__main">
                      <strong>{printer.name}</strong>
                      <span className="hint-text">
                        {printerAddress(printer)} · {printer.paper_width_chars} columns
                        {printer.copies > 1 ? ` · ${printer.copies} copies` : ''}
                      </span>
                      <span className="hint-text">
                        {printer.docket_kinds
                          .map((kind) => kind.replace(/_/g, ' ').toLowerCase())
                          .join(', ') || 'nothing selected'}
                      </span>
                      {printer.last_error && (
                        <span className="print-job-error">{printer.last_error}</span>
                      )}
                    </div>
                    <div className="printer-row__actions">
                      <button
                        className="secondary-button"
                        onClick={() => void test(printer)}
                        type="button"
                      >
                        Test print
                      </button>
                      <button
                        className="secondary-button"
                        onClick={() => openPrinter(agent.id, printer)}
                        type="button"
                      >
                        Edit
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}

            {agent.printers.length > 0 && (
              // One PC can drive a kitchen printer and a counter printer, so
              // this stays — but only once the first one exists, or it
              // competes with the setup call to action above.
              <button
                className="secondary-button"
                onClick={() => openPrinter(agent.id, null)}
                type="button"
              >
                <Plus aria-hidden size={15} /> Add another printer to this PC
              </button>
            )}
          </section>
        );
      })}

      {agents.length > 0 && (
        <section className="admin-surface">
          <h2>Recent tickets</h2>
          <p className="hint-text">
            Where &ldquo;nothing printed&rdquo; gets its answer. A failure says what to check.
          </p>
          <ResponsiveTable
            columns={jobColumns}
            emptyDescription="Tickets appear here as orders are paid for."
            emptyTitle="No tickets yet"
            errorTitle="Tickets didn't load"
            keyExtractor={(job) => job.id}
            // On a phone each row collapses to a title and a subtitle. The
            // ticket kind is the title because that is what somebody is
            // scanning for; the printer and the time are the detail.
            mobileStatus={(job) => <StatusPill status={job.status} />}
            mobileSubtitle={(job) =>
              `${job.printer_name ?? 'unknown printer'} · ${formatDate(
                job.printed_at ?? job.created_at,
              )}`
            }
            mobileTitle={(job) => job.kind.replace(/_/g, ' ').toLowerCase()}
            rows={jobs}
          />
        </section>
      )}

      {/* --- pairing ------------------------------------------------------ */}
      {pairOpen && (
        <Modal
          className="modal-card--compact"
          labelledBy="pair-printer-title"
          onClose={() => setPairOpen(false)}
        >
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">Printing</span>
              <h2 id="pair-printer-title">
                {pairing ? 'Type this code on the kitchen PC' : 'Add a printer'}
              </h2>
              <p className="hint-text">
                {pairing
                  ? 'The agent asks for this once, then remembers the PC.'
                  : 'A code pairs one PC to one branch. It works once and lasts ten minutes.'}
              </p>
            </div>
            <button
              aria-label="Close"
              className="modal-close"
              onClick={() => setPairOpen(false)}
              type="button"
            >
              &times;
            </button>
          </div>
        {pairing ? (
          <div className="pairing-code">
            <p className="hint-text">For {pairing.branch}</p>
            <div className="pairing-code__digits">
              <span>{pairing.code}</span>
              <button
                className="secondary-button"
                onClick={() => {
                  void navigator.clipboard?.writeText(pairing.code);
                  onToast('Copied', 'The code is on your clipboard.', 'info');
                }}
                type="button"
              >
                <Copy aria-hidden size={15} /> Copy
              </button>
            </div>
            <p className="hint-text">
              Expires {formatDate(pairing.expiresAt)}. It works once.
            </p>
            <ol className="pairing-steps">
              <li>On the kitchen PC, run QuickBitePrintAgent.exe.</li>
              <li>Enter the server address, then this code.</li>
              <li>Come back here and add the printer&rsquo;s address.</li>
            </ol>
            <p className="hint-text">
              For a PC that should print after every restart, run install.ps1 instead —
              INSTALL.txt beside it has the one command.
            </p>
          </div>
        ) : (
          <div className="form-grid modal-card__body">
            <label className="field">
              <span>Branch</span>
              <select onChange={(e) => setPairBranch(e.target.value)} value={pairBranch}>
                {locations.map((location) => (
                  <option key={location.id} value={location.id}>
                    {location.branch_name}
                  </option>
                ))}
              </select>
              <small>A printer sits in one room, so it belongs to one branch.</small>
            </label>
            <label className="field">
              <span>What to call this PC</span>
              <input
                maxLength={120}
                onChange={(e) => setPairName(e.target.value)}
                value={pairName}
              />
              <small>You will see this name on this page.</small>
            </label>
          </div>
        )}
        <div className="form-grid__wide modal-actions">
          <button className="secondary-button" onClick={() => setPairOpen(false)} type="button">
            {pairing ? 'Done' : 'Cancel'}
          </button>
            {!pairing && (
              <button className="primary-button" onClick={() => void createCode()} type="button">
                Get a code
              </button>
            )}
          </div>
        </Modal>
      )}

      {/* --- printer form ------------------------------------------------- */}
      {printerModal && (
        <Modal
          busy={saving}
          className="modal-card--compact"
          labelledBy="printer-form-title"
          onClose={() => setPrinterModal(null)}
        >
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">Printer</span>
              <h2 id="printer-form-title">
                {printerModal.printer ? 'Edit printer' : 'Add a printer'}
              </h2>
              <p className="hint-text">
                Where the tickets come out, and which ones.
              </p>
            </div>
            <button
              aria-label="Close"
              className="modal-close"
              onClick={() => setPrinterModal(null)}
              type="button"
            >
              &times;
            </button>
          </div>
        <div className="form-grid modal-card__body printer-form">
          <label className="field">
            <span>Name</span>
            <input
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Kitchen"
              value={form.name}
            />
            {formErrors.name && <small className="field__error">{formErrors.name}</small>}
          </label>

          <label className="field">
            <span>How it is connected</span>
            <select
              onChange={(e) =>
                setForm({ ...form, transport: e.target.value as PrinterForm['transport'] })
              }
              value={form.transport}
            >
              <option value="TCP">On the network</option>
              <option value="WINDOWS">Plugged into this PC</option>
            </select>
            <small>
              {form.transport === 'TCP'
                ? 'The printer has its own IP address. Works with the PC locked and nobody signed in.'
                : 'A USB printer, through Windows. It cannot be seen before anyone logs in, so the agent must be installed with -AtLogon.'}
            </small>
          </label>

          {form.transport === 'TCP' ? (
            <>
              <label className="field">
                <span>Printer address</span>
                <input
                  onChange={(e) => setForm({ ...form, host: e.target.value })}
                  placeholder="192.168.1.50"
                  value={form.host}
                />
                {formErrors.host && <small className="field__error">{formErrors.host}</small>}
              </label>
              <label className="field">
                <span>Port</span>
                <input
                  onChange={(e) => setForm({ ...form, port: e.target.value })}
                  value={form.port}
                />
                {formErrors.port ? (
                  <small className="field__error">{formErrors.port}</small>
                ) : (
                  <small>9100 for nearly every thermal printer. Some use 515.</small>
                )}
              </label>
            </>
          ) : (
            <label className="field form-grid__wide">
              <span>Windows printer name</span>
              <input
                onChange={(e) => setForm({ ...form, windows_printer_name: e.target.value })}
                placeholder="EPSON TM-T82 Receipt"
                value={form.windows_printer_name}
              />
              {formErrors.windows_printer_name ? (
                <small className="field__error">{formErrors.windows_printer_name}</small>
              ) : (
                <small>Exactly as it appears in Settings &rarr; Printers &amp; scanners.</small>
              )}
            </label>
          )}

          <label className="field">
            <span>Paper width</span>
            <select
              onChange={(e) =>
                setForm({ ...form, paper_width_chars: Number(e.target.value) })
              }
              value={form.paper_width_chars}
            >
              {PAPER_WIDTHS.map((width) => (
                <option key={width.value} value={width.value}>
                  {width.label}
                </option>
              ))}
            </select>
            <small>Wrong width makes every line wrap. Measure the paper if unsure.</small>
          </label>

          <label className="field">
            <span>Copies</span>
            <input
              onChange={(e) => setForm({ ...form, copies: e.target.value })}
              value={form.copies}
            />
            {formErrors.copies && <small className="field__error">{formErrors.copies}</small>}
          </label>

          <fieldset className="field form-grid__wide checkbox-set">
            <legend>What this printer prints</legend>
            {DOCKET_KINDS.map((kind) => (
              <label className="checkbox-row" key={kind.value}>
                <input
                  checked={form.docket_kinds.includes(kind.value)}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      docket_kinds: e.target.checked
                        ? [...form.docket_kinds, kind.value]
                        : form.docket_kinds.filter((value) => value !== kind.value),
                    })
                  }
                  type="checkbox"
                />
                <span>
                  <strong>{kind.label}</strong>
                  <small>{kind.hint}</small>
                </span>
              </label>
            ))}
            {formErrors.docket_kinds && (
              <small className="field__error">{formErrors.docket_kinds}</small>
            )}
          </fieldset>
        </div>
        <div className="form-grid__wide modal-actions">
          <button
            className="secondary-button"
            onClick={() => setPrinterModal(null)}
            type="button"
          >
            Cancel
          </button>
            <button
              className="primary-button"
              disabled={saving}
              onClick={() => void savePrinter()}
              type="button"
            >
              {saving ? 'Saving…' : printerModal.printer ? 'Save' : 'Add printer'}
            </button>
          </div>
        </Modal>
      )}

      <ConfirmDialog
        confirmLabel={toggling?.is_enabled ? 'Switch off' : 'Switch on'}
        description={
          toggling?.is_enabled
            ? 'That PC stops printing on its next check, within about fifteen seconds. ' +
              'Orders still arrive and the tickets are still queued — they will print ' +
              'if you switch it back on.'
            : 'That PC starts printing again on its next check. Anything queued while it ' +
              'was off will come out.'
        }
        onCancel={() => setToggling(null)}
        onConfirm={() => toggling && void toggleAgent(toggling)}
        open={toggling !== null}
        title={toggling?.is_enabled ? 'Switch off this PC?' : 'Switch this PC back on?'}
      />
    </div>
  );
}
