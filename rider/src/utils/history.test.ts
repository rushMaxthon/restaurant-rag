import { dayHeaderIndices, groupByDay } from './history';

const trip = (id: string, endedAt: string, earning: string) =>
  ({ id, ended_at: endedAt, earning } as never);

describe('groupByDay', () => {
  const now = new Date('2026-10-08T18:00:00');

  it('puts a header with the day total before each day', () => {
    const rows = groupByDay(
      [
        trip('a', '2026-10-08T17:00:00', '44.20'),
        trip('b', '2026-10-08T12:00:00', '30.00'),
        trip('c', '2026-10-07T20:00:00', '49.00'),
      ],
      now,
    );
    expect(
      rows.map(r =>
        r.kind === 'day' ? `${r.label}:${r.total}:${r.count}` : r.trip.id,
      ),
    ).toEqual(['Today:74.2:2', 'a', 'b', 'Yesterday:49:1', 'c']);
  });

  it('dates a header older than yesterday, so "Mon" is never ambiguous', () => {
    const [head] = groupByDay([trip('d', '2026-10-05T13:00:00', '40.00')], now);
    expect(head).toMatchObject({ kind: 'day', label: 'Mon, 5 Oct' });
  });

  it('is empty for no trips', () => {
    expect(groupByDay([], now)).toEqual([]);
  });
});

describe('which rows stick to the top while scrolling', () => {
  it('is every day heading and no trip', () => {
    const rows = groupByDay(
      [
        trip('a', '2026-10-09T10:00:00', '40'),
        trip('b', '2026-10-09T09:00:00', '40'),
        trip('c', '2026-10-08T09:00:00', '40'),
      ],
      new Date('2026-10-09T12:00:00'),
    );
    expect(dayHeaderIndices(rows)).toEqual([0, 3]);
  });

  it('is nothing for an empty history', () => {
    expect(dayHeaderIndices([])).toEqual([]);
  });
});
