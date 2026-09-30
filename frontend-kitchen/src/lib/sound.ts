/**
 * The noise a new ticket makes.
 *
 * Synthesised with the WebAudio API rather than shipped as a file: it is two
 * short tones, and a kitchen tablet on bad wifi should not have to fetch an
 * asset to tell somebody food has arrived.
 *
 * **Browsers refuse to play audio until the page has been interacted with.**
 * That is not an error to work around, it is the rule — so the context is
 * created on the first real gesture (`unlock`) and every later call is a no-op
 * if that never happened. A silent board is a recoverable disappointment; a
 * board that throws on its first poll is not.
 *
 * The sign-in button used to be the only gesture that unlocked it, which held
 * only for as long as nobody reloaded. A saved session skips the sign-in
 * screen, so after a reload, a reboot or a crashed tab — the normal life of a
 * wall tablet — the board came back silent with the speaker icon still saying
 * sound was on. `unlockOnAnyGesture` is the fix: every tap anywhere is a
 * chance to unlock, and `isAudioReady` lets the header say so until one lands.
 */

let context: AudioContext | null = null
let enabled = true

type WebAudioWindow = Window & { webkitAudioContext?: typeof AudioContext }

const readinessListeners = new Set<() => void>()

function notifyReadiness() {
  for (const listener of readinessListeners) listener()
}

export function unlock() {
  if (context) {
    // Safari suspends an existing context when the tab is backgrounded, which
    // a wall-mounted screen does every time it sleeps.
    if (context.state !== 'running') {
      void context.resume().then(notifyReadiness, () => undefined)
    }
    return
  }
  try {
    const Ctor = window.AudioContext ?? (window as WebAudioWindow).webkitAudioContext
    if (!Ctor) return
    context = new Ctor()
    // Created inside a gesture it normally starts running, but Safari can hand
    // back a suspended one; resuming inside the same gesture is what it honours.
    context.addEventListener?.('statechange', notifyReadiness)
    if (context.state !== 'running') {
      void context.resume().then(notifyReadiness, () => undefined)
    }
    notifyReadiness()
  } catch {
    context = null
  }
}

/**
 * Whether a chime would actually be heard right now.
 *
 * Separate from `isEnabled`, which is only what the cook asked for: sound can
 * be switched on and still be blocked by the browser, and that difference is
 * the one the header has to show.
 */
export function isAudioReady(): boolean {
  return context !== null && context.state === 'running'
}

/** For `useSyncExternalStore`: readiness changes in audio callbacks, not in React. */
export function subscribeAudioReady(listener: () => void): () => void {
  readinessListeners.add(listener)
  return () => {
    readinessListeners.delete(listener)
  }
}

/**
 * Unlock on every tap or key press, for as long as the app is mounted.
 *
 * Not removed after the first success, because the context does not stay
 * unlocked: Safari suspends it each time the screen sleeps, and the next tap
 * is what wakes it. Capture phase so a handler that stops propagation cannot
 * swallow the gesture; `unlock` is a no-op when already running.
 */
export function unlockOnAnyGesture(): () => void {
  const events = ['pointerdown', 'keydown'] as const
  for (const event of events) {
    window.addEventListener(event, unlock, { capture: true, passive: true })
  }
  return () => {
    for (const event of events) {
      window.removeEventListener(event, unlock, { capture: true })
    }
  }
}

/** Test seam: forget the context so each test starts from a fresh page. */
export function resetAudioForTests() {
  context = null
  readinessListeners.clear()
}

export function setEnabled(next: boolean) {
  enabled = next
}

export function isEnabled(): boolean {
  return enabled
}

/** Two rising tones — audible over an extractor fan, and over in half a second. */
export function playNewOrderChime() {
  if (!enabled || !context) return
  try {
    const now = context.currentTime
    for (const [index, frequency] of [880, 1318.5].entries()) {
      const oscillator = context.createOscillator()
      const gain = context.createGain()
      oscillator.type = 'sine'
      oscillator.frequency.value = frequency
      const start = now + index * 0.18
      // Ramped rather than switched, because an abrupt gain change is the
      // click you hear on cheap tablet speakers.
      gain.gain.setValueAtTime(0.0001, start)
      gain.gain.exponentialRampToValueAtTime(0.25, start + 0.02)
      gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.16)
      oscillator.connect(gain).connect(context.destination)
      oscillator.start(start)
      oscillator.stop(start + 0.18)
    }
  } catch {
    // Audio is a courtesy. The flash on the ticket is the real signal.
  }
}
