/**
 * The jobs this agent has already printed.
 *
 * The local half of exactly-once, and the server cannot provide it. The
 * server knows a job was handed out; only the agent knows paper came out of
 * the printer. So when a redelivery arrives — a lost acknowledgement, a
 * restart mid-batch, a lease that expired while a slow docket was still
 * printing — this is what stops a kitchen getting the same ticket twice.
 *
 * A capped list rather than a database: the only question ever asked is "have
 * I printed this id", the ids are uuids, and five thousand of them is every
 * ticket a busy restaurant prints in a fortnight. A job older than that
 * cannot still be in the queue, because the server would have given up on it
 * long before.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

import { configDir } from "./config";

const LIMIT = 5000;

function statePath(): string {
  return join(configDir(), "printed.json");
}

export class PrintedLedger {
  private ids: string[] = [];
  private seen = new Set<string>();

  constructor() {
    try {
      const saved = JSON.parse(readFileSync(statePath(), "utf8")) as string[];
      this.ids = Array.isArray(saved) ? saved.slice(-LIMIT) : [];
      this.seen = new Set(this.ids);
    } catch {
      // No ledger yet, or an unreadable one. Starting empty risks reprinting
      // whatever is still queued, which is a far better failure than refusing
      // to print at all.
    }
  }

  has(id: string): boolean {
    return this.seen.has(id);
  }

  add(id: string): void {
    if (this.seen.has(id)) return;
    this.seen.add(id);
    this.ids.push(id);
    if (this.ids.length > LIMIT) {
      const dropped = this.ids.splice(0, this.ids.length - LIMIT);
      for (const old of dropped) this.seen.delete(old);
    }
    this.persist();
  }

  private persist(): void {
    try {
      mkdirSync(dirname(statePath()), { recursive: true });
      writeFileSync(statePath(), JSON.stringify(this.ids), "utf8");
    } catch {
      // A full or read-only disk costs the duplicate protection, not the
      // printing. Losing a ticket is worse than printing one twice.
    }
  }
}
