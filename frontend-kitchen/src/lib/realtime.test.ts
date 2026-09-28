import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Socket } from 'socket.io-client'

import {
  LIVE_POLL_INTERVAL_MS,
  POLL_INTERVAL_MS,
  RealtimeClient,
  coalesce,
  pollIntervalFor,
  refusalAction,
  socketEndpoint,
} from './realtime'

/** Just enough of a Socket.IO client socket to drive the handlers by hand. */
class FakeSocket {
  handlers = new Map<string, ((...args: unknown[]) => void)[]>()
  emitted: { event: string; payload: unknown; ack?: (a: unknown) => void }[] = []
  connected = false
  active = true
  connectCalls = 0
  closed = false

  on(event: string, handler: (...args: unknown[]) => void) {
    this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler])
    return this
  }
  emit(event: string, payload: unknown, ack?: (a: unknown) => void) {
    this.emitted.push({ event, payload, ack })
    return this
  }
  connect() {
    this.connectCalls += 1
    return this
  }
  disconnect() {
    this.connected = false
    return this
  }
  close() {
    this.closed = true
    return this
  }
  removeAllListeners() {
    this.handlers.clear()
    return this
  }
  fire(event: string, ...args: unknown[]) {
    for (const handler of this.handlers.get(event) ?? []) handler(...args)
  }
}

function setup() {
  const socket = new FakeSocket()
  const onChange = vi.fn()
  const onSignOut = vi.fn()
  const connect = vi.fn(() => socket as unknown as Socket)
  const client = new RealtimeClient({
    apiBaseUrl: 'http://localhost:8000/api',
    auth: () => ({ token: 't' }),
    onChange,
    onSignOut,
    connect,
    coalesceMs: 10,
  })
  client.start()
  return { socket, onChange, onSignOut, connect, client }
}

describe('socketEndpoint', () => {
  it('puts the API prefix in the path, not the URL', () => {
    // In the URL, Socket.IO would read `/api` as a namespace.
    expect(socketEndpoint('http://localhost:8000/api')).toEqual({
      url: 'http://localhost:8000',
      path: '/api/socket.io',
    })
    expect(socketEndpoint('https://api.example.com/api/')).toEqual({
      url: 'https://api.example.com',
      path: '/api/socket.io',
    })
  })
})

describe('refusalAction', () => {
  it('signs out on auth, stops on a permanent refusal, retries the rest', () => {
    expect(refusalAction('auth')).toBe('sign-out')
    expect(refusalAction('realtime_disabled')).toBe('give-up')
    expect(refusalAction('forbidden')).toBe('give-up')
    expect(refusalAction('invalid_restaurant_id')).toBe('give-up')
    expect(refusalAction('unavailable')).toBe('retry')
  })
})

describe('pollIntervalFor', () => {
  it('only slows the poll while a push can actually arrive', () => {
    expect(pollIntervalFor('live')).toBe(LIVE_POLL_INTERVAL_MS)
    for (const status of ['connecting', 'offline', 'disabled'] as const) {
      expect(pollIntervalFor(status)).toBe(POLL_INTERVAL_MS)
    }
  })
})

describe('RealtimeClient', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('connects over WebSocket only, under the API prefix', () => {
    const { connect } = setup()
    const [url, options] = connect.mock.calls[0] as unknown as [string, Record<string, unknown>]
    expect(url).toBe('http://localhost:8000')
    expect(options.path).toBe('/api/socket.io')
    expect(options.transports).toEqual(['websocket'])
  })

  it('refetches on every connect, because pushes sent while away are lost', () => {
    const { socket, onChange, client } = setup()
    socket.fire('connect')
    vi.advanceTimersByTime(20)
    expect(client.getStatus()).toBe('live')
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('coalesces a burst of pushes into one refetch', () => {
    const { socket, onChange } = setup()
    for (let i = 0; i < 6; i += 1) socket.fire('order:updated', { order_id: String(i % 3) })
    vi.advanceTimersByTime(20)
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith(['0', '1', '2'])
  })

  it('reports a reconnect as "anything may have changed"', () => {
    const { socket, onChange } = setup()
    socket.fire('order:updated', { order_id: 'a' })
    socket.fire('connect')
    vi.advanceTimersByTime(20)
    expect(onChange).toHaveBeenCalledWith(null)
  })

  it('signs out when the server refuses the token', () => {
    const { socket, onSignOut } = setup()
    socket.active = false
    socket.fire('connect_error', new Error('auth'))
    expect(onSignOut).toHaveBeenCalledTimes(1)
    expect(socket.closed).toBe(true)
  })

  it('stops retrying, and keeps polling, when realtime is off server-side', () => {
    const { socket, client, onSignOut } = setup()
    socket.active = false
    socket.fire('connect_error', new Error('realtime_disabled'))
    vi.advanceTimersByTime(60000)
    expect(client.getStatus()).toBe('disabled')
    expect(socket.connectCalls).toBe(0)
    expect(onSignOut).not.toHaveBeenCalled()
  })

  it('retries a transient refusal later', () => {
    const { socket, client } = setup()
    socket.active = false
    socket.fire('connect_error', new Error('unavailable'))
    expect(client.getStatus()).toBe('offline')
    vi.advanceTimersByTime(15000)
    expect(socket.connectCalls).toBe(1)
  })

  it('leaves network errors to Socket.IO’s own backoff', () => {
    const { socket, client } = setup()
    socket.active = true
    socket.fire('connect_error', new Error('websocket error'))
    vi.advanceTimersByTime(60000)
    expect(client.getStatus()).toBe('offline')
    expect(socket.connectCalls).toBe(0)
  })

  it('tries once more after a server-side disconnect, so a dead session is refused', () => {
    const { socket, client } = setup()
    socket.fire('connect')
    socket.fire('disconnect', 'io server disconnect')
    expect(client.getStatus()).toBe('offline')
    expect(socket.connectCalls).toBe(1)
  })

  it('signs out on session:revoked', () => {
    const { socket, onSignOut } = setup()
    socket.fire('session:revoked', { reason: 'session_revoked' })
    expect(onSignOut).toHaveBeenCalledTimes(1)
  })

  it('reconnects if a branch change is refused, so the server’s scope stands', () => {
    const { socket, client } = setup()
    socket.connected = true
    client.resubscribe({ restaurant_location_id: 'b2' })
    const sent = socket.emitted.find((entry) => entry.event === 'subscribe')
    expect(sent?.payload).toEqual({ restaurant_location_id: 'b2' })
    sent?.ack?.({ ok: false, error: 'forbidden' })
    expect(socket.connectCalls).toBe(1)
  })

  it('notifies status listeners', () => {
    const { socket, client } = setup()
    const listener = vi.fn()
    client.subscribe(listener)
    socket.fire('connect')
    expect(listener).toHaveBeenCalled()
  })
})

describe('coalesce', () => {
  it('fires once per window and can be cancelled', () => {
    vi.useFakeTimers()
    const fn = vi.fn()
    const c = coalesce(fn, 50)
    c.call()
    c.call()
    vi.advanceTimersByTime(60)
    expect(fn).toHaveBeenCalledTimes(1)
    c.call()
    c.cancel()
    vi.advanceTimersByTime(60)
    expect(fn).toHaveBeenCalledTimes(1)
    vi.useRealTimers()
  })
})
