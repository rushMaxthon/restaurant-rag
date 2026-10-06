/**
 * The loop: poll, print, acknowledge. Forever, quietly.
 *
 * Written to survive the things that actually happen in a restaurant rather
 * than the things that are easy to handle: the printer is switched off at
 * closing, the router reboots at 3am, somebody unplugs the network cable to
 * vacuum, the PC sleeps, the server is redeployed mid-ticket.
 *
 * Three properties it holds:
 *
 * **One ticket at a time, per printer, in order.** A kitchen reads tickets in
 * the order orders arrived, and two sockets to one print head interleave
 * bytes into gibberish.
 *
 * **A printed ticket is never printed twice.** The server hands out a job id;
 * the ledger remembers what came out of the printer. A redelivery — a lost
 * acknowledgement, a restart mid-batch, a lease that expired while a slow
 * docket was still going — is skipped and re-acked.
 *
 * **A failure is reported in a sentence the owner can act on.** It lands in
 * `print_jobs.last_error` and then on their screen, so "ECONNREFUSED" is not
 * an answer.
 */

import { hostname } from "node:os";

import { AgentApi, ApiRefusal, type JobPayload, type PrinterConfig } from "./api";
import type { AgentConfig } from "./config";
import { toEscPos, toPlainText } from "./render/escpos";
import { PrintedLedger } from "./state";
import { sendTcp } from "./transports/tcp";
import { sendWindows } from "./transports/windows";

export const AGENT_VERSION = "0.1.0";

export interface Logger {
  info(message: string): void;
  warn(message: string): void;
  error(message: string): void;
}

/** How long to wait after a failure, growing to a ceiling. */
function backoff(consecutiveFailures: number): number {
  // 5s, 10s, 20s, 40s, 80s, then a minute and a half forever. Fast enough
  // that a brief outage costs one ticket's delay; slow enough that a server
  // down for an hour is not hammered by every restaurant at once.
  return Math.min(5_000 * 2 ** Math.min(consecutiveFailures, 4), 90_000);
}

export class PrintRunner {
  private readonly api: AgentApi;
  private readonly ledger = new PrintedLedger();
  private printers = new Map<string, PrinterConfig>();
  private failures = 0;
  private stopped = false;
  private wake: (() => void) | null = null;

  constructor(
    private readonly config: AgentConfig,
    private readonly log: Logger,
  ) {
    this.api = new AgentApi(config.serverUrl, config.agentToken, config.storefrontHost);
  }

  /**
   * Interrupt the wait and poll now.
   *
   * What the realtime hint calls. The socket makes a ticket arrive in about a
   * second; the interval underneath is what makes it arrive at all when the
   * socket is down.
   */
  pokeNow(): void {
    this.wake?.();
  }

  stop(): void {
    this.stopped = true;
    this.wake?.();
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.wake = null;
        resolve();
      }, ms);
      this.wake = () => {
        clearTimeout(timer);
        this.wake = null;
        resolve();
      };
    });
  }

  async run(): Promise<void> {
    this.log.info(
      `Agent ${AGENT_VERSION} started for ${this.config.restaurantName ?? "restaurant"}` +
        `${this.config.branchName ? ` / ${this.config.branchName}` : ""}`,
    );

    // Announced once at startup so an agent that was installed and never
    // reached the server is visible in the admin as "paired, never seen"
    // rather than indistinguishable from one that is simply idle.
    await this.beat();

    while (!this.stopped) {
      let waitMs = 15_000;
      try {
        const reply = await this.api.poll();
        this.failures = 0;
        this.printers = new Map(reply.printers.map((printer) => [printer.id, printer]));
        waitMs = Math.max(1, reply.poll_after_seconds) * 1000;

        for (const job of reply.jobs) {
          if (this.stopped) break;
          await this.handle(job);
        }
      } catch (error) {
        waitMs = await this.handleRefusal(error);
        if (waitMs < 0) return;
      }
      await this.sleep(waitMs);
    }
  }

  /** One ticket, start to finish. */
  private async handle(job: JobPayload): Promise<void> {
    if (this.ledger.has(job.id)) {
      // Already on paper. Re-acked rather than ignored, because the reason it
      // came back is almost certainly that the first acknowledgement did not
      // arrive — and leaving it unacked means it returns forever.
      this.log.info(`Job ${job.id.slice(0, 8)} already printed; re-acknowledging`);
      await this.api.ack(job.id, true).catch(() => undefined);
      return;
    }

    const printer = this.printers.get(job.printer_id);
    if (!printer) {
      // The server queued work for a printer it then stopped telling us
      // about. Reported rather than dropped silently, because the owner is
      // the only one who can reconcile it.
      await this.fail(
        job,
        "This agent has no configuration for the printer this ticket was queued on. " +
          "Check the Printers page.",
      );
      return;
    }

    try {
      const copies = Math.max(1, job.copies || printer.copies || 1);
      for (let copy = 0; copy < copies; copy += 1) {
        await this.send(printer, job);
      }
      // The ledger is written BEFORE the acknowledgement, deliberately. If
      // this process dies between the two, the job comes back and is skipped;
      // the other order would reprint it.
      this.ledger.add(job.id);
      await this.api.ack(job.id, true);
      this.log.info(
        `Printed ${job.kind} ${job.id.slice(0, 8)} on ${printer.name}` +
          (copies > 1 ? ` (${copies} copies)` : ""),
      );
    } catch (error) {
      await this.fail(job, (error as Error).message);
    }
  }

  private async send(printer: PrinterConfig, job: JobPayload): Promise<void> {
    if (printer.transport === "WINDOWS") {
      if (!printer.windows_printer_name) {
        throw new Error("This printer is set to Windows but has no printer name saved.");
      }
      await sendWindows(toPlainText(job.document), printer.windows_printer_name);
      return;
    }
    if (!printer.host) {
      throw new Error("This printer is set to network but has no address saved.");
    }
    await sendTcp(toEscPos(job.document), printer.host, printer.port ?? 9100);
  }

  private async fail(job: JobPayload, message: string): Promise<void> {
    this.log.error(`Job ${job.id.slice(0, 8)}: ${message}`);
    // Best effort. If the acknowledgement cannot be delivered the job's lease
    // simply expires and it is served again, which is the behaviour wanted.
    await this.api.ack(job.id, false, message).catch(() => undefined);
  }

  /** Returns how long to wait, or -1 to stop entirely. */
  private async handleRefusal(error: unknown): Promise<number> {
    if (error instanceof ApiRefusal) {
      if (error.kind === "unauthenticated") {
        this.log.error(
          `${error.message} This agent will stop until it is paired again.`,
        );
        return -1;
      }
      if (error.kind === "disabled") {
        // Not an error to retry quickly: a human has to turn it back on. But
        // it does keep checking, so switching it on in the admin brings the
        // printer back without anyone touching the PC.
        this.log.warn(`${error.message} Checking again in five minutes.`);
        return 300_000;
      }
      this.failures += 1;
      const waitMs = backoff(this.failures);
      this.log.warn(`${error.message} Retrying in ${Math.round(waitMs / 1000)}s.`);
      return waitMs;
    }
    this.failures += 1;
    this.log.error(`Unexpected failure: ${(error as Error).message}`);
    return backoff(this.failures);
  }

  private async beat(): Promise<void> {
    try {
      const reply = await this.api.heartbeat({ agent_version: AGENT_VERSION });
      if (!reply.auto_print_enabled) {
        // Said out loud, because otherwise a correctly installed agent polling
        // a queue it will never be served looks exactly like a broken one.
        this.log.warn(
          "Auto-printing is switched off for this restaurant, so nothing will print yet. " +
            "The tickets are being queued and can be seen in the admin panel.",
        );
      }
    } catch (error) {
      this.log.warn(`Could not announce this agent: ${(error as Error).message}`);
    }
  }

  get knownPrinters(): PrinterConfig[] {
    return [...this.printers.values()];
  }

  static describeHost(): { hostname: string; agent_version: string } {
    return { hostname: hostname(), agent_version: AGENT_VERSION };
  }
}
