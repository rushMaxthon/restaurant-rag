import { describe, expect, it } from "vitest";

import {
  BEAT_EVERY_MS,
  VISITOR_KEY,
  startHeartbeat,
  visitorId,
  type HeartbeatEnv,
} from "./visitor";

/**
 * The storefront's half of "real visitor counts, not random or repeated"
 * (2026-10-07). The server counts one row per visitor per day; these rules
 * make sure the browser gives it one stable id per person and beats only
 * while somebody is actually looking.
 */

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (key: string) => data[key] ?? null,
    setItem: (key: string, value: string) => {
      data[key] = value;
    },
  };
}

const UUID = "3f1c2b8e-9d4a-4f6b-8c2e-1a2b3c4d5e6f";

describe("the visitor id", () => {
  it("is made once and then reused, so a reload is the same visitor", () => {
    const storage = memoryStorage();
    let made = 0;
    const make = () => {
      made += 1;
      return UUID;
    };
    expect(visitorId(storage, make)).toBe(UUID);
    expect(visitorId(storage, make)).toBe(UUID);
    expect(made).toBe(1);
    expect(storage.data[VISITOR_KEY]).toBe(UUID);
  });

  it("replaces a stored value that is not an id", () => {
    const storage = memoryStorage({ [VISITOR_KEY]: "garbage" });
    expect(visitorId(storage, () => UUID)).toBe(UUID);
  });

  it("still works when storage is blocked (private mode)", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    const first = visitorId(blocked, () => UUID);
    expect(first).toBe(UUID);
    // Same id for the rest of the page's life, not a new one per beat.
    expect(visitorId(blocked, () => "11111111-1111-4111-8111-111111111111")).toBe(UUID);
  });
});

/** A fake clock, visibility and timers. */
function fakeEnv(visible = true) {
  let now = 0;
  let isVisible = visible;
  const intervals: Array<{ ms: number; cb: () => void; next: number }> = [];
  const visibleListeners: Array<() => void> = [];
  const env: HeartbeatEnv = {
    isVisible: () => isVisible,
    now: () => now,
    every: (ms, cb) => {
      const entry = { ms, cb, next: now + ms };
      intervals.push(entry);
      return () => intervals.splice(intervals.indexOf(entry), 1);
    },
    onVisible: (cb) => {
      visibleListeners.push(cb);
      return () => visibleListeners.splice(visibleListeners.indexOf(cb), 1);
    },
  };
  return {
    env,
    advance(ms: number) {
      const end = now + ms;
      for (;;) {
        const due = intervals
          .filter((entry) => entry.next <= end)
          .sort((a, b) => a.next - b.next)[0];
        if (!due) break;
        now = due.next;
        due.next += due.ms;
        due.cb();
      }
      now = end;
    },
    hide() {
      isVisible = false;
    },
    show() {
      isVisible = true;
      for (const listener of [...visibleListeners]) listener();
    },
    listeners: () => intervals.length + visibleListeners.length,
  };
}

describe("the heartbeat", () => {
  it("beats when the page opens and then once a minute", () => {
    const clock = fakeEnv();
    let beats = 0;
    startHeartbeat(() => (beats += 1), clock.env);
    expect(beats).toBe(1);
    clock.advance(BEAT_EVERY_MS * 3);
    expect(beats).toBe(4);
  });

  it("is silent while the tab is in the background", () => {
    const clock = fakeEnv();
    let beats = 0;
    startHeartbeat(() => (beats += 1), clock.env);
    clock.hide();
    clock.advance(BEAT_EVERY_MS * 5);
    expect(beats).toBe(1);
  });

  it("does not count a page opened in a background tab until it is looked at", () => {
    const clock = fakeEnv(false);
    let beats = 0;
    startHeartbeat(() => (beats += 1), clock.env);
    expect(beats).toBe(0);
    clock.advance(30_000);
    clock.show();
    expect(beats).toBe(1);
  });

  it("does not beat twice for flicking between tabs", () => {
    const clock = fakeEnv();
    let beats = 0;
    startHeartbeat(() => (beats += 1), clock.env);
    clock.hide();
    clock.advance(1000);
    clock.show();
    expect(beats).toBe(1);
  });

  it("stops completely when the page goes away", () => {
    const clock = fakeEnv();
    let beats = 0;
    const stop = startHeartbeat(() => (beats += 1), clock.env);
    stop();
    clock.advance(BEAT_EVERY_MS * 3);
    clock.show();
    expect(beats).toBe(1);
    expect(clock.listeners()).toBe(0);
  });
});
