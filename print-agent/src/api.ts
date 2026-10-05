/**
 * The four calls this agent makes, and nothing else.
 *
 * Outbound only, which is the whole reason the design works in a restaurant:
 * no port forwarding, no static address, nothing to configure on a router
 * that somebody's cousin set up in 2019.
 *
 * The refusal codes are a contract, not noise. They decide whether the agent
 * re-pairs, stops, or waits — and getting that wrong is how an agent either
 * hammers a server it will never satisfy or goes quiet when a human could
 * have fixed it in a minute.
 */

import type { TicketDocument } from "./layout";

export interface PrinterConfig {
  id: string;
  name: string;
  transport: "TCP" | "WINDOWS";
  host: string | null;
  port: number | null;
  windows_printer_name: string | null;
  paper_width_chars: number;
  copies: number;
  docket_kinds: string[];
}

export interface JobPayload {
  id: string;
  printer_id: string;
  kind: string;
  document: TicketDocument;
  copies: number;
}

export interface PollResponse {
  jobs: JobPayload[];
  printers: PrinterConfig[];
  poll_after_seconds: number;
}

export interface PairResponse {
  agent_id: string;
  agent_token: string;
  restaurant_name: string;
  branch_name: string;
  printers: PrinterConfig[];
}

/** Why the server would not answer, in the terms the run loop acts on. */
export type RefusalKind =
  /** Token unrecognised. Nothing to retry; a human must pair again. */
  | "unauthenticated"
  /** Switched off in the admin. Stop, and wait for somebody to turn it on. */
  | "disabled"
  /** Anything else — network, 5xx, a proxy. Keep trying. */
  | "transient";

export class ApiRefusal extends Error {
  constructor(
    readonly kind: RefusalKind,
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ApiRefusal";
  }
}

export class AgentApi {
  constructor(
    private readonly serverUrl: string,
    private readonly token: string | null,
    private readonly storefrontHost?: string | undefined,
  ) {}

  private url(path: string): string {
    return `${this.serverUrl.replace(/\/+$/, "")}${path}`;
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...((init.headers as Record<string, string> | undefined) ?? {}),
    };
    if (this.token) headers["Authorization"] = `Bearer ${this.token}`;
    // Only for a deployment serving several tenants on one address. In
    // production each restaurant has its own subdomain and the URL carries
    // it, so this is normally absent.
    if (this.storefrontHost) headers["X-Forwarded-Host"] = this.storefrontHost;

    let response: Response;
    try {
      response = await fetch(this.url(path), {
        ...init,
        headers,
        // Long enough for a slow link, short enough that a wedged connection
        // does not stall the print loop until somebody reboots the PC.
        signal: AbortSignal.timeout(20_000),
      });
    } catch (error) {
      throw new ApiRefusal(
        "transient",
        `Could not reach ${this.serverUrl}: ${(error as Error).message}`,
      );
    }

    if (response.status === 401) {
      throw new ApiRefusal(
        "unauthenticated",
        "This agent's token was not accepted. Pair it again from the Printers page.",
        401,
      );
    }
    if (response.status === 403) {
      throw new ApiRefusal(
        "disabled",
        "This agent is switched off in the admin panel.",
        403,
      );
    }
    if (!response.ok) {
      const body = await response.text().catch(() => "");
      throw new ApiRefusal(
        "transient",
        `${response.status} from ${path}${body ? `: ${body.slice(0, 300)}` : ""}`,
        response.status,
      );
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  static pair(
    serverUrl: string,
    body: { code: string; hostname?: string; agent_version?: string },
    storefrontHost?: string,
  ): Promise<PairResponse> {
    return new AgentApi(serverUrl, null, storefrontHost).request<PairResponse>(
      "/print-agents/pair",
      { method: "POST", body: JSON.stringify(body) },
    );
  }

  poll(): Promise<PollResponse> {
    return this.request<PollResponse>("/print-agents/me/jobs");
  }

  /**
   * Say whether a ticket printed.
   *
   * Idempotent on the server, so re-acking a redelivery is a normal path
   * rather than something to avoid — which is what lets the local ledger be
   * the authority on what actually came out of the printer.
   */
  ack(jobId: string, printed: boolean, error?: string): Promise<void> {
    return this.request<void>(`/print-agents/me/jobs/${jobId}/ack`, {
      method: "POST",
      body: JSON.stringify({ printed, error: error ?? null }),
    });
  }

  heartbeat(body: {
    agent_version?: string;
    printer_errors?: Record<string, string | null>;
  }): Promise<{ auto_print_enabled: boolean; poll_after_seconds: number }> {
    return this.request("/print-agents/me/heartbeat", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }
}
