/**
 * The 401 path, which used to strand the board.
 *
 * A rejected token cleared localStorage but told nobody, so React kept the old
 * session and the board sat on "Not updating" until somebody reloaded it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, getToken, onSessionExpired, readSession, storeSession, type KitchenSession } from './api'

const SESSION: KitchenSession = {
  token: 'token-a',
  role: 'KITCHEN',
  fullName: 'Cook',
  restaurantId: 'r1',
  restaurantLocationId: null,
}

function memoryStorage() {
  const data = new Map<string, string>()
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  }
}

function respondWith(status: number, onFetch?: () => void) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      onFetch?.()
      return new Response(JSON.stringify({ detail: 'Could not validate credentials' }), { status })
    }),
  )
}

const scope = { restaurantId: 'r1', locationId: null }

describe('session expiry', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', memoryStorage())
    storeSession(SESSION)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('clears the stored session and tells listeners on a 401', async () => {
    respondWith(401)
    const listener = vi.fn()
    const stop = onSessionExpired(listener)

    await expect(api.ordersByStatus('PLACED', scope, 'x')).rejects.toMatchObject({ status: 401 })

    expect(listener).toHaveBeenCalledTimes(1)
    expect(getToken()).toBeNull()
    expect(readSession()).toBeNull()
    stop()
  })

  it('does not treat a 403 as an expired session', async () => {
    // 403 on this API means "outside your scope", and the token is still good.
    respondWith(403)
    const listener = vi.fn()
    const stop = onSessionExpired(listener)

    await expect(api.ordersByStatus('PLACED', scope, 'x')).rejects.toMatchObject({ status: 403 })

    expect(listener).not.toHaveBeenCalled()
    expect(getToken()).toBe('token-a')
    stop()
  })

  it('ignores a late 401 for a token that has since been replaced', async () => {
    // Somebody signed in again while the old request was in flight.
    respondWith(401, () => storeSession({ ...SESSION, token: 'token-b' }))
    const listener = vi.fn()
    const stop = onSessionExpired(listener)

    await expect(api.ordersByStatus('PLACED', scope, 'x')).rejects.toMatchObject({ status: 401 })

    expect(listener).not.toHaveBeenCalled()
    expect(getToken()).toBe('token-b')
    stop()
  })

  it('stops notifying once unsubscribed', async () => {
    respondWith(401)
    const listener = vi.fn()
    onSessionExpired(listener)()

    await expect(api.ordersByStatus('PLACED', scope, 'x')).rejects.toBeDefined()

    expect(listener).not.toHaveBeenCalled()
  })
})
