/**
 * The Printers screen's own rules, where they can be tested without a form.
 *
 * The same split `services/kitchenStaff.ts` makes, for the same reason: a
 * limit restated beside a field catches a mistake there rather than as a 422
 * after Save. None of it is the authority — the `transport_is_exhaustive` and
 * `paper_width_is_known` CHECKs on `printers` are, and the API refuses a
 * duplicate address — but an owner should not need a round trip to learn that
 * a network printer needs an address.
 */

import type { PrinterTransport, PrintJobKind, PrinterForm } from '../types/printing';

/** 32 is 58mm paper, 48 is 80mm, 42 is the other common 80mm font. */
export const PAPER_WIDTHS = [
  { value: 32, label: '32 columns — 58mm paper' },
  { value: 42, label: '42 columns — 80mm, small font' },
  { value: 48, label: '48 columns — 80mm paper' },
] as const;

/**
 * What each kind of ticket is for, in the owner's terms.
 *
 * Written as what it does rather than what it is called, because "void slip"
 * means nothing to somebody setting up a printer for the first time.
 */
export const DOCKET_KINDS: { value: PrintJobKind; label: string; hint: string }[] = [
  {
    value: 'KITCHEN_DOCKET',
    label: 'Kitchen docket',
    hint: 'What to cook. No prices.',
  },
  {
    value: 'CUSTOMER_BILL',
    label: 'Customer bill',
    hint: 'The itemised total, to hand over.',
  },
  {
    value: 'VOID_SLIP',
    label: 'Cancellation slip',
    hint: 'Tells the kitchen to stop, when a docket is already out.',
  },
];

export const EMPTY_PRINTER_FORM: PrinterForm = {
  name: '',
  transport: 'TCP',
  host: '',
  port: '9100',
  windows_printer_name: '',
  paper_width_chars: 48,
  copies: '1',
  docket_kinds: ['KITCHEN_DOCKET', 'VOID_SLIP'],
};

export type PrinterFormErrors = Partial<Record<keyof PrinterForm, string>>;

export function validatePrinterForm(form: PrinterForm): PrinterFormErrors {
  const errors: PrinterFormErrors = {};

  if (!form.name.trim()) {
    errors.name = 'Give it a name — "Kitchen" or "Counter".';
  } else if (form.name.trim().length > 120) {
    errors.name = 'Keep it under 120 characters.';
  }

  if (form.transport === 'TCP') {
    const host = form.host.trim();
    if (!host) {
      errors.host = "The printer's IP address, for example 192.168.1.50.";
    } else if (!/^[A-Za-z0-9.\-_]+$/.test(host)) {
      // Not a strict IP check: a hostname is valid here, and some printers are
      // reached by one. This only rejects what cannot be an address at all.
      errors.host = 'That does not look like an address or a hostname.';
    }
    const port = Number(form.port);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      errors.port = 'A port between 1 and 65535. Nearly always 9100.';
    }
  } else if (!form.windows_printer_name.trim()) {
    errors.windows_printer_name =
      'The name exactly as it appears in Settings → Printers & scanners.';
  }

  const copies = Number(form.copies);
  if (!Number.isInteger(copies) || copies < 1 || copies > 5) {
    errors.copies = 'Between 1 and 5.';
  }

  if (form.docket_kinds.length === 0) {
    // A printer subscribed to nothing is configured, online, and will never
    // print — the most confusing state available.
    errors.docket_kinds = 'Choose at least one, or this printer will never print anything.';
  }

  return errors;
}

export function hasErrors(errors: PrinterFormErrors): boolean {
  return Object.keys(errors).length > 0;
}

/** The form as the API wants it. */
export function buildPrinterPayload(form: PrinterForm) {
  const tcp = form.transport === 'TCP';
  return {
    name: form.name.trim(),
    transport: form.transport,
    host: tcp ? form.host.trim() : null,
    port: tcp ? Number(form.port) : null,
    windows_printer_name: tcp ? null : form.windows_printer_name.trim(),
    paper_width_chars: form.paper_width_chars,
    copies: Number(form.copies),
    docket_kinds: form.docket_kinds,
  };
}

/** Where this printer is, for a table cell. */
export function printerAddress(printer: {
  transport: PrinterTransport;
  host: string | null;
  port: number | null;
  windows_printer_name: string | null;
}): string {
  if (printer.transport === 'TCP') {
    return printer.host ? `${printer.host}:${printer.port ?? 9100}` : 'no address';
  }
  return printer.windows_printer_name || 'no printer name';
}

/**
 * Is this agent currently connected?
 *
 * An agent heartbeats on start and polls on an interval, so silence for more
 * than a couple of minutes means it has stopped — the PC is off, asleep, or
 * the process died. Two minutes rather than thirty seconds because a poll is
 * fifteen seconds apart and a slow link should not flicker the badge.
 *
 * `null` means never seen at all, which is a different and more actionable
 * fact: it was paired and never started.
 */
export function agentLiveness(lastSeenAt: string | null): 'online' | 'offline' | 'never' {
  if (!lastSeenAt) return 'never';
  const seen = new Date(lastSeenAt).getTime();
  if (Number.isNaN(seen)) return 'never';
  return Date.now() - seen < 120_000 ? 'online' : 'offline';
}

/** "2 minutes ago", for a last-seen cell. */
export function sinceLabel(value: string | null): string {
  if (!value) return 'never';
  const then = new Date(value).getTime();
  if (Number.isNaN(then)) return 'never';
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}
