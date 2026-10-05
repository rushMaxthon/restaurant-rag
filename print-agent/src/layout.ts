/**
 * A ticket document as characters on paper of a known width.
 *
 * A deliberate port of `backend/app/services/print/layout.py`, and the two
 * must agree. `layout.test.ts` checks them against the same documents for
 * exactly that reason: if they disagree about where a long address breaks,
 * the preview an owner approves is not the ticket a kitchen gets.
 *
 * It carries one rule, and the rule exists because of a real ticket:
 *
 *     NO PEANUTS - severe allergy. Ring the bell twice
 *     A-31 Rangdarshan Society, Near Dhanmora, Katarga
 *
 * The note lost its final character and the address lost "Surat, Gujarat,
 * 395004" — the part a rider needs. Both because the layout truncated at the
 * paper's width instead of wrapping. So: **a ticket never silently drops
 * text.** The only thing allowed to be shortened is a key's label, and never
 * its value, because half a phone number is a rider who cannot call.
 *
 * Used twice here: the ESC/POS renderer emits these already-wrapped rows
 * rather than letting the printer wrap (it breaks mid-word, wherever it
 * lands), and the Windows spooler transport sends this output directly.
 */

export type Align = "left" | "center" | "right";
export type Size = "normal" | "double";

/** One instruction in a ticket, as the server stored it on the job. */
export interface Line {
  t: string;
  v?: string | null;
  k?: string | null;
  qty?: number | null;
  mods?: string[];
  align?: Align;
  bold?: boolean;
  size?: Size;
}

export interface TicketDocument {
  width: number;
  kind?: string;
  lines: Line[];
}

/**
 * Break a string to fit, on word boundaries where it can.
 *
 * A word longer than the paper is split rather than left to overflow — a
 * 45-character street name on 32-column paper has to break somewhere, and
 * breaking it beats losing its tail. Returns at least one row, so an empty
 * string still occupies the row the document asked for.
 */
export function wrap(value: string, width: number): string[] {
  if (width <= 0) return [value];

  const out: string[] = [];
  for (const paragraph of value.split("\n")) {
    const words = paragraph.split(/\s+/).filter(Boolean);
    if (words.length === 0) {
      out.push("");
      continue;
    }
    let current = "";
    for (let word of words) {
      while (word.length > width) {
        if (current) {
          out.push(current);
          current = "";
        }
        out.push(word.slice(0, width));
        word = word.slice(width);
      }
      if (!current) current = word;
      else if (current.length + 1 + word.length <= width) current = `${current} ${word}`;
      else {
        out.push(current);
        current = word;
      }
    }
    if (current) out.push(current);
  }
  return out.length > 0 ? out : [""];
}

/**
 * How many characters of this line fit on the paper.
 *
 * Half, for a double-size line. Not a detail: ESC/POS double height is also
 * double WIDTH, so "*** CANCELLED ***" at 48 columns needs 17 of a 24-column
 * budget and the printer wraps it itself, mid-banner. Wrapping here means we
 * choose the break.
 */
function effectiveWidth(line: Line, width: number): number {
  return line.size === "double" ? Math.floor(width / 2) : width;
}

function layOutKv(line: Line, width: number): string[] {
  const value = line.v ?? "";
  let label = line.k ?? "";
  let gap = width - label.length - value.length;
  if (gap < 1) {
    // The label gives way, never the value. "Phone" cut to "Pho" still
    // reads; a phone number missing two digits does not.
    label = label.slice(0, Math.max(0, width - value.length - 1));
    gap = Math.max(1, width - label.length - value.length);
  }
  return [`${label}${" ".repeat(gap)}${value}`];
}

function layOutItem(line: Line, width: number): string[] {
  const head = `${line.qty ?? ""} x ${line.v ?? ""}`;
  const wrapped = wrap(head, width);
  // Continuation of a wrapped dish name is aligned under the NAME rather
  // than the quantity, so it does not read as a second dish.
  const out = [
    wrapped[0] ?? "",
    ...wrapped.slice(1).map((rest) => `    ${rest}`.slice(0, width)),
  ];
  for (const mod of line.mods ?? []) {
    const parts = wrap(mod, Math.max(1, width - 4));
    out.push(`    ${parts[0] ?? ""}`);
    out.push(...parts.slice(1).map((rest) => `      ${rest}`));
  }
  return out;
}

function pad(row: string, width: number, align: Align): string {
  if (align === "center") {
    const left = Math.floor((width - row.length) / 2);
    if (left <= 0) return row;
    return `${" ".repeat(left)}${row}${" ".repeat(Math.max(0, width - row.length - left))}`;
  }
  if (align === "right") return row.padStart(width, " ");
  return row;
}

function layOutText(line: Line, width: number): string[] {
  // Wrapped at the line's own effective width, then padded across the WHOLE
  // paper — or a double-size banner would sit in the left half of the ticket.
  return wrap(line.v ?? "", effectiveWidth(line, width)).map((row) =>
    pad(row, width, line.align ?? "left"),
  );
}

/** The whole ticket, as the paper will show it. */
export function layOut(document: TicketDocument): string {
  const width = document.width;
  const out: string[] = [];

  for (const line of document.lines ?? []) {
    switch (line.t) {
      case "rule":
        out.push((line.v || "-").repeat(width));
        break;
      case "blank":
        out.push("");
        break;
      case "cut":
        // An instruction to the printer, not a mark on the paper.
        out.push("");
        break;
      case "kv":
        out.push(...layOutKv(line, width));
        break;
      case "item":
        out.push(...layOutItem(line, width));
        break;
      default:
        // Anything this build does not recognise is printed as text rather
        // than dropped. A ticket printing imperfectly beats one not printing.
        out.push(...layOutText(line, width));
    }
  }

  return out.join("\n");
}

/** One line on its own, which is how the ESC/POS renderer styles row by row. */
export function layOutLine(line: Line, width: number): string[] {
  return layOut({ width, lines: [line] }).split("\n");
}
