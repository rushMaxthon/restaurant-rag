/** What the printing API returns and accepts. Mirrors `app/api/printing.py`. */

export type PrinterTransport = 'TCP' | 'WINDOWS';

export type PrintJobKind = 'KITCHEN_DOCKET' | 'CUSTOMER_BILL' | 'VOID_SLIP' | 'TEST';

export type PrintJobStatus = 'QUEUED' | 'CLAIMED' | 'PRINTED' | 'FAILED';

export interface Printer {
  id: string;
  name: string;
  transport: PrinterTransport;
  host: string | null;
  port: number | null;
  windows_printer_name: string | null;
  paper_width_chars: number;
  copies: number;
  docket_kinds: string[];
  is_enabled: boolean;
  /**
   * The last failure, in a sentence written for the owner.
   *
   * This is where "nothing printed" gets its answer, which is why the backend
   * phrases every provider failure as advice rather than as an exception.
   */
  last_error: string | null;
  last_printed_at: string | null;
}

export interface PrintAgent {
  id: string;
  name: string;
  restaurant_location_id: string;
  branch_name: string | null;
  hostname: string | null;
  agent_version: string | null;
  last_seen_at: string | null;
  is_enabled: boolean;
  printers: Printer[];
}

export interface PrintJob {
  id: string;
  order_id: string | null;
  printer_id: string;
  printer_name: string | null;
  kind: string;
  source: string;
  status: PrintJobStatus;
  attempts: number;
  last_error: string | null;
  created_at: string;
  printed_at: string | null;
}

export interface PairingCode {
  code: string;
  expires_at: string;
  branch_name: string;
}

/** The add/edit form, as strings because that is what inputs hold. */
export interface PrinterForm {
  name: string;
  transport: PrinterTransport;
  host: string;
  port: string;
  windows_printer_name: string;
  paper_width_chars: number;
  copies: string;
  docket_kinds: PrintJobKind[];
}
