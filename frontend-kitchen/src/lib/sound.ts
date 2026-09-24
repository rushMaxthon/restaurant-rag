/**
 * The noise a new ticket makes.
 *
 * Synthesised with the WebAudio API rather than shipped as a file: it is two
 * short tones, and a kitchen tablet on bad wifi should not have to fetch an
 * asset to tell somebody food has arrived.
 *
 * **Browsers refuse to play audio until the page has been interacted with.**
 * That is not an error to work around, it is the rule — so the context is
 * created on the first real gesture (`unlock`, called from the sign-in button)
 * and every later call is a no-op if that never happened. A silent board is a
 * recoverable disappointment; a board that throws on its first poll is not.
 */

let context: AudioContext | null = null
let enabled = true

type WebAudioWindow = Window & { webkitAudioContext?: typeof AudioContext }

export function unlock() {
  if (context) {
    // Safari suspends an existing context when the tab is backgrounded, which
    // a wall-mounted screen does every time it sleeps.
    void context.resume().catch(() => undefined)
    return
  }
  try {
    const Ctor = window.AudioContext ?? (window as WebAudioWindow).webkitAudioContext
    if (!Ctor) return
    context = new Ctor()
  } catch {
    context = null
  }
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
