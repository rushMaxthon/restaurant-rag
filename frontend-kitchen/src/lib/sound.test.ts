/**
 * Audio unlock after a reload.
 *
 * The sign-in button was the only gesture that unlocked audio, and a saved
 * session skips sign-in — so a reloaded board stayed silent with sound "on".
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  isAudioReady,
  resetAudioForTests,
  subscribeAudioReady,
  unlock,
  unlockOnAnyGesture,
} from './sound'

/** A context that starts in whatever state the browser would hand back. */
class FakeAudioContext {
  static initialState: AudioContextState = 'running'
  state: AudioContextState = FakeAudioContext.initialState
  resume = vi.fn(async () => {
    this.state = 'running'
  })
  addEventListener = vi.fn()
}

function fakeWindow() {
  const handlers = new Map<string, EventListener>()
  return {
    AudioContext: FakeAudioContext,
    handlers,
    addEventListener: vi.fn((event: string, handler: EventListener) => handlers.set(event, handler)),
    removeEventListener: vi.fn((event: string) => handlers.delete(event)),
  }
}

describe('audio unlock', () => {
  let win: ReturnType<typeof fakeWindow>

  beforeEach(() => {
    resetAudioForTests()
    FakeAudioContext.initialState = 'running'
    win = fakeWindow()
    vi.stubGlobal('window', win)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('is not ready before any gesture — the state after a reload', () => {
    expect(isAudioReady()).toBe(false)
  })

  it('unlocks on any tap or key press, not only the sign-in button', () => {
    const stop = unlockOnAnyGesture()
    expect([...win.handlers.keys()].sort()).toEqual(['keydown', 'pointerdown'])

    win.handlers.get('pointerdown')!(new Event('pointerdown'))
    expect(isAudioReady()).toBe(true)

    stop()
    expect(win.handlers.size).toBe(0)
  })

  it('tells subscribers when audio becomes ready', () => {
    const listener = vi.fn()
    const stop = subscribeAudioReady(listener)
    unlock()
    expect(listener).toHaveBeenCalled()
    stop()
  })

  it('resumes a suspended context on the next gesture', async () => {
    // Safari can hand back a suspended context, and suspends it on sleep.
    FakeAudioContext.initialState = 'suspended'
    const listener = vi.fn()
    subscribeAudioReady(listener)

    unlock()
    await Promise.resolve()
    await Promise.resolve()

    expect(isAudioReady()).toBe(true)
    expect(listener).toHaveBeenCalled()
  })
})
