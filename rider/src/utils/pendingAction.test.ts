import { decodePending, encodePending, PENDING_MAX_AGE_MS } from './pendingAction';

const saved = {
  tripId: 'trip-1',
  action: 'picked-up' as const,
  id: 'act-1',
  savedAt: '2026-10-09T10:00:00.000Z',
};

describe('a trip step waiting for signal', () => {
  const now = new Date('2026-10-09T10:05:00Z');

  it('survives being written and read back', () => {
    expect(decodePending(encodePending(saved), 'trip-1', now)).toEqual(saved);
  });

  it('keeps the delivery code with a delivered step', () => {
    const delivered = { ...saved, action: 'delivered' as const, otp: '7166' };
    expect(decodePending(encodePending(delivered), 'trip-1', now)?.otp).toBe('7166');
  });

  it('belongs to one trip: another trip never replays it', () => {
    expect(decodePending(encodePending(saved), 'trip-2', now)).toBeNull();
  });

  it('is dropped once it is too old to mean anything', () => {
    const late = new Date(Date.parse(saved.savedAt) + PENDING_MAX_AGE_MS + 1);
    expect(decodePending(encodePending(saved), 'trip-1', late)).toBeNull();
  });

  it('treats nothing, junk or an unknown step as nothing to resume', () => {
    expect(decodePending(null, 'trip-1', now)).toBeNull();
    expect(decodePending('{not json', 'trip-1', now)).toBeNull();
    expect(decodePending(encodePending({ ...saved, action: 'teleport' as never }), 'trip-1', now)).toBeNull();
  });
});
