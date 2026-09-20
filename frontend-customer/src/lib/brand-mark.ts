/**
 * The monogram in the round badge, from the restaurant's own name.
 *
 * It was the literal "BB" in four places — the site header on every page, the
 * branch chooser that is the first thing a new visitor sees, and twice on the
 * concierge. Bangkok Bowl's initials, worn by every tenant on this platform,
 * including a dhokla shop in Surat. The header's accessible label said
 * "Bangkok Bowl home" to every screen reader, and the restaurant name beside
 * the badge fell back to "Bangkok Bowl" too.
 *
 * The invariant worth keeping is narrow and absolute: the badge must never
 * contradict the name printed next to it. So both come from one string.
 */

/** Words that are not what a restaurant is called, and make poor initials. */
const SKIP = new Set(["the", "a", "an", "of", "and", "&"]);

export function brandInitials(name: string | null | undefined): string {
  const words = (name ?? "")
    .split(/[\s\-–—]+/)
    .map((word) => word.replace(/[^\p{L}\p{N}]/gu, ""))
    .filter((word) => word.length > 0 && !SKIP.has(word.toLowerCase()));

  if (words.length === 0) {
    // Nothing to draw. The caller renders no badge rather than a placeholder
    // that would just be a different restaurant's initials by another route.
    return "";
  }
  if (words.length === 1) {
    // One word gets two of its own letters — a single letter in a round badge
    // reads as an icon that failed to load.
    return words[0]!.slice(0, 2).toUpperCase();
  }
  return (words[0]![0]! + words[1]![0]!).toUpperCase();
}
