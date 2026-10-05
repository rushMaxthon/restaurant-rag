/**
 * The print agent: a background process that turns paid orders into paper.
 *
 *     agent pair --server https://orders.example.com/api --code 123456
 *     agent run
 *     agent run --console      (log to the terminal as well as the file)
 *     agent status
 *
 * `run` is what the Scheduled Task created by `installer/install.ps1`
 * invokes at boot. Everything else is for the person installing it.
 */

import { appendFileSync, mkdirSync } from "node:fs";
import { hostname } from "node:os";
import { join } from "node:path";

import { AgentApi } from "./api";
import { configDir, configPath, readConfig, writeConfig } from "./config";
import { interactive } from "./interactive";
import { connectRealtime } from "./realtime";
import { AGENT_VERSION, PrintRunner, type Logger } from "./runner";

/**
 * Logs to a file, and to the console only when asked.
 *
 * The file matters more than it sounds. The Windows note in this repo's
 * CLAUDE.md records an afternoon lost to a Celery worker whose traceback went
 * to a hidden window's stderr: "a WhatsApp message arrived, the webhook
 * returned 200, the task left the queue and no reply was sent" — and every
 * health check said the worker was fine. A background process on a restaurant
 * PC has no console at all, so a log file is the only way anybody ever finds
 * out why a ticket did not print.
 */
function makeLogger(toConsole: boolean): Logger {
  const path = join(configDir(), "agent.log");
  try {
    mkdirSync(configDir(), { recursive: true });
  } catch {
    // Keep going: a console-only agent is still useful, and refusing to start
    // because a log file could not be made would be the wrong trade.
  }

  const write = (level: string, message: string) => {
    const line = `${new Date().toISOString()} ${level} ${message}`;
    if (toConsole) console.log(line);
    try {
      appendFileSync(path, `${line}\n`, "utf8");
    } catch {
      // Full or read-only disk. Not worth stopping printing over.
    }
  };

  return {
    info: (message) => write("INFO ", message),
    warn: (message) => write("WARN ", message),
    error: (message) => write("ERROR", message),
  };
}

function flag(name: string): string | undefined {
  const index = process.argv.indexOf(`--${name}`);
  if (index === -1) return undefined;
  return process.argv[index + 1];
}

function has(name: string): boolean {
  return process.argv.includes(`--${name}`);
}

async function pair(): Promise<number> {
  const server = flag("server") ?? readConfig()?.serverUrl;
  const code = flag("code");
  if (!server || !code) {
    console.error(
      "Usage: agent pair --server <https://host/api> --code <six digits>\n\n" +
        "Get the code from the admin panel: Printers > Add a printer.",
    );
    return 2;
  }

  const host = flag("storefront-host");
  try {
    const reply = await AgentApi.pair(
      server,
      { code, hostname: hostname(), agent_version: AGENT_VERSION },
      host,
    );
    writeConfig({
      serverUrl: server,
      agentToken: reply.agent_token,
      agentId: reply.agent_id,
      restaurantName: reply.restaurant_name,
      branchName: reply.branch_name,
      ...(host ? { storefrontHost: host } : {}),
    });
    console.log(`Paired with ${reply.restaurant_name} / ${reply.branch_name}.`);
    console.log(`Saved to ${configPath()}`);
    if (reply.printers.length === 0) {
      // Worth saying plainly: pairing succeeds with no printer configured,
      // and the agent will then run correctly and print nothing, which looks
      // identical to being broken.
      console.log(
        "\nNo printers are configured for this agent yet. Add one in the admin panel " +
          "(Printers > this agent > Add printer), then run `agent run`.",
      );
    } else {
      for (const printer of reply.printers) {
        const where =
          printer.transport === "TCP"
            ? `${printer.host}:${printer.port ?? 9100}`
            : printer.windows_printer_name;
        console.log(`  ${printer.name}: ${where} at ${printer.paper_width_chars} columns`);
      }
    }
    return 0;
  } catch (error) {
    console.error(`Pairing failed: ${(error as Error).message}`);
    return 1;
  }
}

async function run(forceConsole = false): Promise<number> {
  const config = readConfig();
  if (!config) {
    console.error(
      `This agent is not paired yet. No config at ${configPath()}.\n` +
        "Run: agent pair --server <https://host/api> --code <six digits>",
    );
    return 2;
  }

  const log = makeLogger(forceConsole || has("console"));
  const runner = new PrintRunner(config, log);

  // The socket is an accelerator, nothing more: it tells the runner to poll
  // now. Everything still arrives on the interval if it never connects, which
  // is why a failure here is logged and otherwise ignored.
  const realtime = connectRealtime(config, log, () => runner.pokeNow());

  const shutdown = (signal: string) => {
    log.info(`Stopping on ${signal}`);
    realtime.close();
    runner.stop();
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));

  // A background process must not die on an unhandled rejection: Node's
  // default is to exit, and an agent that exits at 7pm because one fetch
  // rejected oddly is an agent nobody trusts. The Scheduled Task would
  // restart it, but only at the next boot.
  process.on("unhandledRejection", (reason) =>
    log.error(`Unhandled rejection: ${String(reason)}`),
  );

  await runner.run();
  realtime.close();
  return 0;
}

function status(): number {
  const config = readConfig();
  if (!config) {
    console.log(`Not paired. No config at ${configPath()}.`);
    return 1;
  }
  console.log(`Agent    ${config.agentId}`);
  console.log(`Server   ${config.serverUrl}`);
  console.log(`For      ${config.restaurantName ?? "?"} / ${config.branchName ?? "?"}`);
  console.log(`Config   ${configPath()}`);
  console.log(`Log      ${join(configDir(), "agent.log")}`);
  return 0;
}

async function main(): Promise<number> {
  const command = process.argv[2];
  switch (command) {
    case "pair":
      return pair();
    case "run":
      return run();
    case "status":
      return status();
    case undefined:
      // Double-clicked. Printing usage and exiting means Windows allocates
      // a console, writes five lines and closes it before anybody can read
      // a word - which is exactly what happened. So no arguments means the
      // interactive setup, which asks what it needs and holds the window
      // open on every path, including the failures.
      return interactive(() => run(true));
    default:
      console.error(
        `QuickBite print agent ${AGENT_VERSION}\n\n` +
          "  agent pair --server <url> --code <six digits>\n" +
          "  agent run [--console]\n" +
          "  agent status\n\n" +
          "Run it with no arguments for guided setup.\n",
      );
      return 2;
  }
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(error);
    process.exit(1);
  },
);
