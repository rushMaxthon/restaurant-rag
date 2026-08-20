/**
 * Minimal chat text helpers.
 *
 * The assistant model emphasizes dish names with `**bold**` Markdown; the
 * chat bubble renders plain text, so the raw markers were visible in the UI.
 */

export interface ChatTextSegment {
  text: string;
  bold: boolean;
}

/**
 * Splits a reply into plain/bold segments for `**bold**` spans.
 *
 * Unpaired `**` markers (possible mid-stream) are stripped rather than
 * displayed, so the raw marker never flashes in the UI.
 */
export function splitBoldSegments(text: string): ChatTextSegment[] {
  if (!text.includes('**')) {
    return [{ text, bold: false }];
  }
  const parts = text.split(/\*\*([^*]+)\*\*/g);
  const segments: ChatTextSegment[] = [];
  parts.forEach((part, index) => {
    const bold = index % 2 === 1;
    const cleaned = bold ? part : part.replace(/\*\*/g, '');
    if (cleaned) {
      segments.push({ text: cleaned, bold });
    }
  });
  return segments.length > 0 ? segments : [{ text: '', bold: false }];
}

/** Drops repeated entries (same id) while keeping first-seen order. */
export function dedupeById<T extends { id: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter(item => {
    if (seen.has(item.id)) {
      return false;
    }
    seen.add(item.id);
    return true;
  });
}
