/**
 * "Only the newest answer may land", for state that several callers refresh
 * at once - a poll, a focus refresh, a socket hint and a button can all be in
 * flight together, and an older response arriving last would undo a newer
 * one (an order that was just taken coming back to the board; a rider who
 * just went online flicking back to offline).
 */
export function sequencer() {
  let latest = 0;
  return {
    /** Call before a request; keep the ticket. */
    start: () => ++latest,
    /** Whether the answer to this ticket is still the newest thing to show. */
    isLatest: (ticket: number) => ticket === latest,
    /** A value set directly (not fetched) beats every request already out. */
    invalidate: () => {
      latest += 1;
    },
  };
}
