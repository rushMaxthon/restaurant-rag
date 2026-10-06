/**
 * What happens when somebody double-clicks the executable.
 *
 * It used to print usage and exit, which from a double-click means Windows
 * allocates a console, writes five lines into it and closes it before anybody
 * can read a word. Reported exactly that way: "it's open and close, not able
 * to see anything".
 *
 * A CLI is still the right shape for the install script to drive, so the
 * arguments all keep working. This is the other audience: a person at a
 * kitchen PC who has been sent a file and told to run it. For them the
 * executable asks the two questions it needs, does the work, and — above all
 * — **never closes without being told to**, so whatever went wrong is still
 * on screen.
 */

import { createInterface } from "node:readline/promises";
import { existsSync, readFileSync } from "node:fs";
import { hostname } from "node:os";
import { join } from "node:path";

import { AgentApi } from "./api";
import { configDir, configPath, readConfig, writeConfig } from "./config";
import { AGENT_VERSION } from "./runner";

const line = "-".repeat(62);

function banner(): void {
  console.log("");
  console.log("  QuickBite print agent");
  console.log(`  ${line}`);
  console.log("");
}

/**
 * Hold the window open.
 *
 * The whole reason this module exists. Called on every exit path, including
 * the failures — especially the failures, because a message nobody can read
 * is the same as no message.
 */
async function pause(ask: ReturnType<typeof createInterface>): Promise<void> {
  console.log("");
  await ask.question("  Press Enter to close. ");
}

function tail(path: string, lines: number): string[] {
  if (!existsSync(path)) return [];
  try {
    return readFileSync(path, "utf8").trimEnd().split("\n").slice(-lines);
  } catch {
    return [];
  }
}

export async function interactive(runAgent: () => Promise<number>): Promise<number> {
  const ask = createInterface({ input: process.stdin, output: process.stdout });
  try {
    banner();
    const config = readConfig();

    if (!config) {
      console.log("  This PC is not set up yet. Two things are needed:");
      console.log("");
      console.log("    1. the server address, which your platform gave you");
      console.log("    2. a six-digit code from the admin panel:");
      console.log("         Printers  >  Add a printer  >  choose the branch");
      console.log("");
      console.log("  Codes last ten minutes, so get it just before doing this.");
      console.log("");

      const server = (await ask.question("  Server address: ")).trim();
      if (!server) {
        console.log("\n  Nothing entered, so nothing was changed.");
        await pause(ask);
        return 1;
      }
      const code = (await ask.question("  Six-digit code: ")).trim();
      if (!code) {
        console.log("\n  Nothing entered, so nothing was changed.");
        await pause(ask);
        return 1;
      }

      // A deployment serving several restaurants on one address needs this;
      // one with a subdomain per restaurant does not. Asked last and
      // optional, so the common case is two questions rather than three.
      const host = (
        await ask.question("  Storefront host (press Enter to skip): ")
      ).trim();

      console.log("");
      console.log("  Pairing...");
      try {
        const reply = await AgentApi.pair(
          server,
          { code, hostname: hostname(), agent_version: AGENT_VERSION },
          host || undefined,
        );
        writeConfig({
          serverUrl: server,
          agentToken: reply.agent_token,
          agentId: reply.agent_id,
          restaurantName: reply.restaurant_name,
          branchName: reply.branch_name,
          ...(host ? { storefrontHost: host } : {}),
        });
        console.log(`  Paired with ${reply.restaurant_name} / ${reply.branch_name}.`);
        if (reply.printers.length === 0) {
          // Said plainly, because this is the state that looks like success
          // and prints nothing.
          console.log("");
          console.log("  No printer is set up for this PC yet. Add one in the admin");
          console.log("  panel (Printers > this agent > Add printer) before testing.");
        } else {
          for (const printer of reply.printers) {
            const where =
              printer.transport === "TCP"
                ? `${printer.host}:${printer.port ?? 9100}`
                : printer.windows_printer_name;
            console.log(`    ${printer.name}: ${where} at ${printer.paper_width_chars} columns`);
          }
        }
      } catch (error) {
        console.log("");
        console.log(`  Pairing failed: ${(error as Error).message}`);
        console.log("");
        console.log("  Most likely one of:");
        console.log("    * the code has expired - they last ten minutes");
        console.log("    * the code was already used - each works once");
        console.log("    * the server address is wrong, or this PC cannot reach it");
        await pause(ask);
        return 1;
      }
    } else {
      console.log(`  Set up for ${config.restaurantName ?? "?"} / ${config.branchName ?? "?"}`);
      console.log(`  Server      ${config.serverUrl}`);
      console.log(`  Version     ${AGENT_VERSION}`);
      console.log("");

      const recent = tail(join(configDir(), "agent.log"), 6);
      if (recent.length > 0) {
        console.log("  Last few entries from the log:");
        for (const entry of recent) console.log(`    ${entry}`);
        console.log("");
      }
    }

    console.log(`  ${line}`);
    console.log("");
    console.log("  Start printing now, in this window?");
    console.log("");
    console.log("  Tickets will appear here as they print. Closing this window");
    console.log("  stops it, so for a permanent setup run install.ps1 instead -");
    console.log("  that starts it automatically every time the PC boots.");
    console.log("");

    const answer = (await ask.question("  Start now? [Y/n] ")).trim().toLowerCase();
    if (answer && !answer.startsWith("y")) {
      console.log("");
      console.log("  Nothing started. Run install.ps1 for the permanent setup.");
      await pause(ask);
      return 0;
    }

    // The prompt has to be closed before handing over: the runner's own
    // SIGINT handling is how Ctrl-C stops it, and a live readline would
    // swallow that.
    ask.close();
    console.log("");
    console.log(`  Running. Press Ctrl-C to stop.`);
    console.log("");
    return await runAgent();
  } finally {
    ask.close();
  }
}
