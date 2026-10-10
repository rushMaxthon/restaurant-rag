import React from 'react';
import TestRenderer, { act } from 'react-test-renderer';

import { ApiError } from '@/services/http';

const mockAct = jest.fn();
jest.mock('@/store/SessionProvider', () => ({
  useApi: () => ({ act: mockAct }),
}));
jest.mock('@/services/pendingAction', () => ({
  clearPending: jest.fn(() => Promise.resolve()),
  loadPending: jest.fn(() => Promise.resolve(null)),
  savePending: jest.fn(() => Promise.resolve()),
}));
jest.mock('@react-native-community/netinfo', () => ({
  addEventListener: jest.fn(() => () => undefined),
}));

import { useTripAction } from './useTripAction';

type Hook = ReturnType<typeof useTripAction>;

function mount(onDone: jest.Mock) {
  const out: { hook: Hook | null } = { hook: null };
  function Probe() {
    out.hook = useTripAction('trip-1', onDone);
    return null;
  }
  let renderer: TestRenderer.ReactTestRenderer | null = null;
  act(() => {
    renderer = TestRenderer.create(<Probe />);
  });
  return { out, unmount: () => act(() => renderer?.unmount()) };
}

const offline = () => new ApiError(0, 'offline');

/** Lets the save-then-attempt chain and the request's promise settle. */
async function settle() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

describe('useTripAction', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    mockAct.mockReset();
  });
  afterEach(() => jest.useRealTimers());

  it('stops retrying once the trip screen is gone', async () => {
    let fail: (e: unknown) => void = () => undefined;
    mockAct.mockImplementationOnce(
      () => new Promise((_, reject) => (fail = reject)),
    );
    mockAct.mockRejectedValue(offline());
    const onDone = jest.fn();
    const { out, unmount } = mount(onDone);

    await act(async () => {
      out.hook?.run('picked-up');
      await settle();
    });
    expect(mockAct).toHaveBeenCalledTimes(1);

    // The screen closes while that request is still out; then it fails.
    unmount();
    await act(async () => {
      fail(offline());
      await settle();
      jest.advanceTimersByTime(120_000);
      await settle();
    });
    expect(mockAct).toHaveBeenCalledTimes(1);
  });

  it('never calls back into a screen that has closed', async () => {
    let succeed: (v: unknown) => void = () => undefined;
    mockAct.mockImplementationOnce(
      () => new Promise(resolve => (succeed = resolve)),
    );
    const onDone = jest.fn();
    const { out, unmount } = mount(onDone);
    await act(async () => {
      out.hook?.run('delivered', '4719');
      await settle();
    });
    unmount();
    await act(async () => {
      succeed({ id: 'trip-1', step: 'done' });
      await settle();
    });
    expect(onDone).not.toHaveBeenCalled();
  });

  it('backs off between retries instead of hammering every 3 s', async () => {
    mockAct.mockRejectedValue(offline());
    const { out, unmount } = mount(jest.fn());
    await act(async () => {
      out.hook?.run('arrived-pickup');
      await settle();
    });
    expect(mockAct).toHaveBeenCalledTimes(1);
    const callsAfter = async (ms: number) => {
      await act(async () => {
        jest.advanceTimersByTime(ms);
        await settle();
      });
      return mockAct.mock.calls.length;
    };
    expect(await callsAfter(3_000)).toBe(2); // 3 s
    expect(await callsAfter(5_999)).toBe(2); // not yet: 6 s
    expect(await callsAfter(1)).toBe(3);
    expect(await callsAfter(12_000)).toBe(4); // 12 s
    expect(await callsAfter(24_000)).toBe(5); // 24 s
    expect(await callsAfter(30_000)).toBe(6); // capped at 30 s
    expect(await callsAfter(30_000)).toBe(7);
    unmount();
  });
});
