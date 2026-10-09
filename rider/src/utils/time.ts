/** Whole seconds left until `expiresAt`, never negative, rounded UP so "0" means gone. */
export function secondsLeft(expiresAt: number, now: number): number {
  return Math.max(0, Math.ceil((expiresAt - now) / 1000));
}
