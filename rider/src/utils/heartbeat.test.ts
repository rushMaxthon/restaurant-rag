import { batchToSend } from './heartbeat';

const fix = (at: string) => ({ lat: 21.2, lng: 72.8, accuracy_m: 5, at });

describe('batchToSend', () => {
  const now = new Date('2026-10-08T19:30:00Z');

  it('sends what the GPS saw when the rider moved', () => {
    const queued = [fix('2026-10-08T19:29:50Z')];
    expect(batchToSend(queued, fix('2026-10-08T19:29:50Z'), null, now)).toEqual(
      queued,
    );
  });

  it('repeats the last position, stamped now, for a rider standing still', () => {
    // distanceFilter means "has not moved 15 m": the last fix IS where they are.
    expect(batchToSend([], fix('2026-10-08T19:18:44Z'), null, now)).toEqual([
      { lat: 21.2, lng: 72.8, accuracy_m: 5, at: '2026-10-08T19:30:00.000Z' },
    ]);
  });

  it('sends nothing when the GPS has failed, so the rider honestly reads as silent', () => {
    expect(
      batchToSend(
        [],
        fix('2026-10-08T19:18:44Z'),
        'Location is not available',
        now,
      ),
    ).toEqual([]);
  });

  it('sends nothing before the first fix', () => {
    expect(batchToSend([], null, null, now)).toEqual([]);
  });
});
