/**
 * JSON for a `<script type="application/ld+json">` tag, safe to write raw.
 *
 * The values come from what an owner typed - FAQ answers, the description,
 * the address - and `JSON.stringify` leaves `</script>` and `<!--` intact, so
 * an answer containing them closed the tag and ran the rest as script for
 * every visitor (2026-10-07 security review). Escaping `<`, `>` and `&` as
 * unicode escapes means the HTML parser never sees a tag, while any JSON
 * reader, search engines included, reads back exactly the same strings.
 * U+2028 and U+2029 are escaped too: they end a line in older JavaScript.
 */

// Built from char codes so no editor or shell can turn them into real line
// breaks inside a regex literal, which is what happened the first time.
const LINE_SEPARATOR = new RegExp(String.fromCharCode(0x2028), "g");
const PARAGRAPH_SEPARATOR = new RegExp(String.fromCharCode(0x2029), "g");

export function jsonLd(value: unknown): string {
  return JSON.stringify(value)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(LINE_SEPARATOR, "\\u2028")
    .replace(PARAGRAPH_SEPARATOR, "\\u2029");
}
