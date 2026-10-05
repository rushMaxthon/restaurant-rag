import { order } from '@/test/fixtures';
import { reuseUnchanged } from './reconcile';

describe('reuseUnchanged', () => {
  const a = order({ id: 'a', updated_at: '1' });
  const b = order({ id: 'b', updated_at: '1' });

  it('returns the previous array when a poll changed nothing', () => {
    const previous = [a, b];
    expect(reuseUnchanged(previous, [{ ...a }, { ...b }])).toBe(previous);
  });

  it('keeps unchanged orders as the same objects and swaps in changed ones', () => {
    const moved = { ...b, status: 'ACCEPTED' as const, updated_at: '2' };
    const result = reuseUnchanged([a, b], [{ ...a }, moved]);
    expect(result[0]).toBe(a);
    expect(result[1]).toBe(moved);
  });

  it('notices arrivals, departures and reordering', () => {
    const c = order({ id: 'c', updated_at: '1' });
    expect(reuseUnchanged([a, b], [{ ...a }, { ...b }, c])).toHaveLength(3);
    expect(reuseUnchanged([a, b], [{ ...a }])).toEqual([a]);
    const reordered = reuseUnchanged([a, b], [{ ...b }, { ...a }]);
    expect(reordered).toEqual([b, a]);
    expect(reordered[0]).toBe(b);
  });

  it('compares whole rows when updated_at is missing', () => {
    const plain = order({ id: 'p' });
    expect(reuseUnchanged([plain], [{ ...plain }])[0]).toBe(plain);
    const edited = { ...plain, special_instructions: 'No onion' };
    expect(reuseUnchanged([plain], [edited])[0]).toBe(edited);
  });
});
