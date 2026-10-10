/**
 * The previous value when the new one says the same thing, else the new one.
 *
 * Every poll used to hand React a brand-new object - the Orders board a new
 * empty list every 8 s - so every screen reading RiderProvider re-rendered,
 * tabs in the background included, even when nothing had changed. Returning
 * the same reference lets React skip all of it. API answers are plain JSON,
 * so a structural compare is exact and cheap at these sizes.
 */
export function keepIfSame<T>(prev: T, next: T): T {
  return equal(prev, next) ? prev : next;
}

function equal(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (
    a === null ||
    b === null ||
    typeof a !== 'object' ||
    typeof b !== 'object'
  )
    return false;
  if (Array.isArray(a)) {
    if (!Array.isArray(b) || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) if (!equal(a[i], b[i])) return false;
    return true;
  }
  if (Array.isArray(b)) return false;
  const ka = Object.keys(a as object);
  const kb = Object.keys(b as object);
  if (ka.length !== kb.length) return false;
  for (const key of ka) {
    if (!Object.prototype.hasOwnProperty.call(b, key)) return false;
    if (
      !equal(
        (a as Record<string, unknown>)[key],
        (b as Record<string, unknown>)[key],
      )
    )
      return false;
  }
  return true;
}
