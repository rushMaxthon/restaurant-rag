/**
 * Raw bytes to a printer's own address.
 *
 * Port 9100 is a pipe straight to the print head: no handshake, no reply. A
 * successful write means the bytes left this machine, not that paper moved —
 * which is why a clean send is reported as printed and the owner still has
 * eyes on the printer.
 */

import { createConnection } from "node:net";

export function sendTcp(
  payload: Buffer,
  host: string,
  port: number,
  timeoutMs = 8000,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const socket = createConnection({ host, port });
    let settled = false;

    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      error ? reject(error) : resolve();
    };

    socket.setTimeout(timeoutMs);
    socket.on("timeout", () =>
      finish(
        new Error(
          `The printer at ${host}:${port} accepted a connection but stopped responding. ` +
            `Check it has paper and is not showing an error light.`,
        ),
      ),
    );
    socket.on("error", (error: NodeJS.ErrnoException) => {
      // The sentence an owner reads on the admin screen, not the exception's.
      const hint =
        error.code === "ECONNREFUSED"
          ? ` Nothing is listening on port ${port} — some printers use 515 instead of 9100.`
          : error.code === "EHOSTUNREACH" || error.code === "ETIMEDOUT"
            ? " It may be switched off, or on a different network from this PC."
            : "";
      finish(new Error(`The printer at ${host}:${port} did not answer.${hint}`));
    });
    socket.on("connect", () => {
      // `end` rather than `write`: the printer has no terminator for a job,
      // so closing the connection is what tells it the ticket is complete.
      socket.end(payload, () => finish());
    });
  });
}
