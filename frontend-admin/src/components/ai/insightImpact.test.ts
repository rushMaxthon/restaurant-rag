import { describe, expect, it } from 'vitest';
import { formatImpact, rankInsights } from './insightImpact';
import type { OwnerInsight } from '../../types/app';

function insight(partial: Partial<OwnerInsight> & { id: string }): OwnerInsight {
  return {
    insight_type: 'ITEM_DECLINE',
    severity: 'LOW',
    status: 'NEW',
    title: 't',
    body: 'b',
    dimension: null,
    subject: null,
    score: 0,
    root_cause: null,
    period_start: '2026-05-28',
    period_end: '2026-08-25',
    facts: {},
    created_at: '2026-08-25',
    acknowledged_at: null,
    ...partial,
  } as OwnerInsight;
}

describe('rankInsights', () => {
  // The real shape, taken from a captured /owner/insights/feed response.
  const real = [
    insight({ id: 'daypart', score: 376.77, facts: { absolute_change: -376.77 } }),
    insight({ id: 'item', score: 1328.51, facts: { absolute_change: -1328.51 } }),
    insight({ id: 'surge', score: 195.86, facts: { absolute_change: 195.86 } }),
    insight({ id: 'loc', score: 816.225, facts: { absolute_change: -544.15, stopped_trading: true } }),
  ];

  it('orders by the backend score, strongest first', () => {
    expect(rankInsights(real).map((r) => r.insight.id)).toEqual(['item', 'loc', 'daypart', 'surge']);
  });

  it('measures each finding against the strongest on screen', () => {
    const [first, second] = rankInsights(real);
    expect(first.impact.share).toBe(1);
    expect(second.impact.share).toBeCloseTo(816.225 / 1328.51, 5);
  });

  it('reads the rupee change and its direction from facts', () => {
    const byId = new Map(rankInsights(real).map((r) => [r.insight.id, r.impact]));
    expect(byId.get('item')?.amount).toBe(-1328.51);
    expect(byId.get('item')?.direction).toBe('down');
    expect(byId.get('surge')?.direction).toBe('up');
  });

  it('surfaces a branch that has stopped trading', () => {
    const byId = new Map(rankInsights(real).map((r) => [r.insight.id, r.impact]));
    expect(byId.get('loc')?.stoppedTrading).toBe(true);
    expect(byId.get('item')?.stoppedTrading).toBe(false);
  });

  it('falls back to the rupee change when no score is sent', () => {
    const rows = rankInsights([
      insight({ id: 'a', score: 0, facts: { absolute_change: -900 } }),
      insight({ id: 'b', score: 0, facts: { absolute_change: -100 } }),
    ]);
    expect(rows.map((r) => r.insight.id)).toEqual(['a', 'b']);
  });

  it('does not divide by zero on a completely flat period', () => {
    const rows = rankInsights([insight({ id: 'a', score: 0, facts: {} })]);
    expect(rows[0].impact.share).toBe(0);
    expect(rows[0].impact.direction).toBe('flat');
  });

  it('leaves the caller array untouched', () => {
    const input = [...real];
    rankInsights(input);
    expect(input.map((r) => r.id)).toEqual(real.map((r) => r.id));
  });
});

describe('formatImpact', () => {
  it('signs and groups the figure', () => {
    expect(formatImpact(-1328.51)).toBe('−₹1,329');
    expect(formatImpact(195.86)).toBe('+₹196');
  });
  it('renders nothing when there is no movement to show', () => {
    expect(formatImpact(null)).toBeNull();
    expect(formatImpact(0)).toBeNull();
  });
});
