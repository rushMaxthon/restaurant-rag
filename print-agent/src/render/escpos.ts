/**
 * A ticket document as bytes a thermal printer understands.
 *
 * Deliberately the smallest usable subset of ESC/POS. Every command here is
 * in the original Epson set and has been honoured by every clone for twenty
 * years; anything fancier is where printer compatibility goes to die.
 *
 * Two decisions worth knowing, both of which took a wrong ticket to find:
 *
 * **Line breaks come from `layout.ts`, not from the printer.** Left to itself
 * a printer wraps mid-word wherever the line happens to end, and a delivery
 * address is the wrong thing to let it guess at.
 *
 * **Alignment is baked into the padding, not sent as `ESC a n`.** So this and
 * the Windows spooler path produce the same ticket. One centring its own text
 * and the other receiving pre-padded text would not agree about anything.
 *
 * The currency symbol is NOT handled here. It used to be — transliterating
 * the rupee sign to "Rs." after the server had padded the row for a
 * one-character symbol made `Subtotal ... Rs.100.00` fifty characters wide on
 * 48-column paper, and the printer wrapped the money column. Money is made
 * printer-safe server-side now, in `document.money_str`, before anything
 * counts columns.
 */

import { layOutLine, type Line, type TicketDocument } from "../layout";

const ESC = 0x1b;
const GS = 0x1d;

const INIT = Buffer.from([ESC, 0x40]); // reset: clears state a previous job left
const ALIGN_LEFT = Buffer.from([ESC, 0x61, 0x00]);
const BOLD_ON = Buffer.from([ESC, 0x45, 0x01]);
const BOLD_OFF = Buffer.from([ESC, 0x45, 0x00]);
const SIZE_NORMAL = Buffer.from([GS, 0x21, 0x00]);
// GS ! n — high nibble is width, low nibble height.
const SIZE_DOUBLE = Buffer.from([GS, 0x21, 0x11]);
const FEED = Buffer.from([0x0a]);
// GS V 66 n — feed then partial cut. A printer with no cutter ignores it,
// which is why it is safe to send unconditionally.
const CUT = Buffer.from([GS, 0x56, 0x42, 0x03]);

/**
 * Characters a thermal printer's default code page cannot draw.
 *
 * A safety net for PROSE — a curly quote in a dish name, an en dash in a
 * note — not for currency. Keeping it narrow matters: anything that changes
 * a string's LENGTH after the server has padded it breaks the column
 * arithmetic, so every substitution here is the same width or shorter.
 */
const SAFE: Record<string, string> = {
  "‘": "'",
  "’": "'",
  "“": '"',
  "”": '"',
  "–": "-",
  "—": "-",
  " ": " ",
};

function toPrintable(value: string): string {
  let out = "";
  for (const char of value) {
    if (SAFE[char] !== undefined) out += SAFE[char];
    else if (char.charCodeAt(0) < 0x80) out += char;
    // Anything else is dropped rather than sent as noise. The server already
    // made money and the common punctuation safe, so reaching here means a
    // character nobody planned for — and a missing glyph reads better than a
    // row of boxes.
    else out += "";
  }
  return out;
}

/** One document as printer bytes. */
export function toEscPos(document: TicketDocument): Buffer {
  const chunks: Buffer[] = [INIT];

  for (const line of document.lines ?? []) {
    if (line.t === "cut") {
      chunks.push(FEED, FEED, FEED, CUT);
      continue;
    }
    for (const row of layOutLine(line, document.width)) {
      chunks.push(ALIGN_LEFT);
      chunks.push(line.size === "double" ? SIZE_DOUBLE : SIZE_NORMAL);
      if (line.bold) chunks.push(BOLD_ON);
      chunks.push(Buffer.from(toPrintable(row), "latin1"));
      if (line.bold) chunks.push(BOLD_OFF);
      chunks.push(SIZE_NORMAL, FEED);
    }
  }

  // A document with no explicit cut still has to leave the paper clear of the
  // print head, or the last few lines of every ticket are unreadable until
  // the next one pushes them out.
  const last = document.lines?.[document.lines.length - 1];
  if (last?.t !== "cut") chunks.push(FEED, FEED, FEED, CUT);

  return Buffer.concat(chunks);
}

/** The same document as plain text, for the Windows spooler. */
export function toPlainText(document: TicketDocument): string {
  const rows: string[] = [];
  for (const line of document.lines ?? []) {
    if (line.t === "cut") {
      rows.push("", "", "");
      continue;
    }
    rows.push(...layOutLine(line, document.width).map(toPrintable));
  }
  return rows.join("\r\n");
}

export type { Line, TicketDocument };
