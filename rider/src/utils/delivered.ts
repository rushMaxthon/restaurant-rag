/** The Delivered screen's second button: only when there is somewhere useful to go. */
export function waitingLabel(count: number): string | null {
  if (count <= 0) return null;
  return `${count} order${count === 1 ? '' : 's'} waiting`;
}
