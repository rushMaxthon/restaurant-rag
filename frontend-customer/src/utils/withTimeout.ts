/**
 * A deadline for a promise that might never settle.
 *
 * The pages load their sections with `Promise.all`, and every call in one
 * carries a `.catch()`. That reads as full coverage and is not: `.catch()`
 * handles a REJECTION, and a request that hangs never rejects. When
 * `/recommendations/query` stopped answering, `Promise.all` never resolved, the
 * `finally` that clears the loading flag never ran, and a page whose other four
 * responses had arrived in milliseconds sat in skeletons indefinitely.
 *
 * The fix is to make "too slow" indistinguishable from "failed", because the
 * `.catch(() => [])` chains already at every call site know what to do with a
 * failure. Nothing else has to change for a hang to degrade into an empty
 * section instead of a dead page.
 *
 * Deliberately NOT an `AbortController`: aborting is the right tool when the
 * caller no longer wants the result, but here the request may well be in
 * flight and about to succeed. This only stops the UI waiting on it — a late
 * answer is discarded rather than cancelled, which keeps the helper usable
 * against any promise, including ones from APIs that take no signal.
 */

export class TimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TimeoutError';
  }
}

export function withTimeout<T>(promise: Promise<T>, ms: number, label = 'request'): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;

  const deadline = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      reject(new TimeoutError(`${label} did not answer within ${ms}ms`));
    }, ms);
  });

  // `finally` rather than clearing on each path: the timer has to go when the
  // promise settles EITHER way, or it holds the event loop open and, inside a
  // component, fires after unmount.
  return Promise.race([promise, deadline]).finally(() => clearTimeout(timer));
}
