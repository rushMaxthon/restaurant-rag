/**
 * Through the Windows spooler, for a printer attached by USB.
 *
 * Plain text, not ESC/POS. A queue created from a Windows driver expects the
 * driver's own language and renders raw escape codes as literal gibberish; a
 * queue installed as "Generic / Text Only" takes text and the printer applies
 * its own defaults. No bold, no double height, but legible — which is the
 * whole requirement for this transport.
 *
 * **The limitation that decides the installer.** A Windows service runs in
 * Session 0, which has no user profile and therefore cannot see per-user
 * installed printers. An agent configured this way has to run at LOGON as
 * the user who owns the printer, not at startup as SYSTEM. `install.ps1`
 * takes `-AtLogon` for exactly this, and this is the comment that explains
 * why the flag exists.
 */

import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

export function sendWindows(text: string, printerName: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const file = join(mkdtempSync(join(tmpdir(), "qbprint-")), "ticket.txt");
    writeFileSync(file, text, "utf8");

    // `-LiteralPath` so a printer name or path containing brackets is not
    // read as a wildcard, and the name is passed as a bound parameter rather
    // than interpolated into the command — a printer called `Kitchen'; rm` is
    // unlikely and trivial to make impossible.
    const script =
      "param($File,$Printer) Get-Content -LiteralPath $File | Out-Printer -Name $Printer";
    const child = spawn(
      "powershell",
      ["-NoProfile", "-NonInteractive", "-Command", script, "-File", file, "-Printer", printerName],
      { windowsHide: true },
    );

    let stderr = "";
    child.stderr?.on("data", (chunk) => (stderr += String(chunk)));
    child.on("error", (error) =>
      reject(new Error(`Could not run PowerShell to print: ${error.message}`)),
    );
    child.on("close", (code) => {
      if (code === 0) return resolve();
      reject(
        new Error(
          `The Windows spooler refused the job for "${printerName}". ` +
            (stderr.trim() ||
              "Check the printer name matches Settings > Printers & scanners exactly, " +
                "and that this agent runs as a signed-in user rather than at startup."),
        ),
      );
    });
  });
}
