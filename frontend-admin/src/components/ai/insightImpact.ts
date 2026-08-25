import type { OwnerInsight } from '../../types/app';

/**
 * Ranking and magnitude for a finding, read from fields the API already sends.
 *
 * The feed previously rendered every finding at identical weight in whatever
 * order it arrived, so a branch that had stopped trading sat level with a ₹71
 * dish. `score` is the backend's own ranking - roughly the absolute change,
 * weighted by how much the finding type matters - and `facts.absolute_change`
 * is the rupee figure behind it. Both were being discarded in the component.
 */
export interface InsightImpact {
  /** Backend ranking. Higher is more worth reading. */
  score: number;
  /** Signed rupee change, when the finding carries one. */
  amount: number | null;
  /** Share of this finding's score against the largest on screen, 0–1. */
  share: number;
  /** Whether the movement helped or hurt. */
  direction: 'up' | 'down' | 'flat';
  /** A branch that has stopped taking orders entirely. */
  stoppedTrading: boolean;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * Sorts findings by the backend's score, strongest first, and measures each
 * against the strongest so the bar widths are comparable within one period.
 *
 * Returns a new array; the caller's order is left alone.
 */
export function rankInsights(
  insights: OwnerInsight[],
): Array<{ insight: OwnerInsight; impact: InsightImpact }> {
  const scored = insights.map((insight) => {
    const facts = (insight.facts ?? {}) as Record<string, unknown>;
    const amount = num(facts.absolute_change);
    // `score` is the intended ranking. Falling back to the rupee change keeps
    // ordering sensible for any finding type that does not carry one.
    const score = num(insight.score) ?? Math.abs(amount ?? 0);
    return {
      insight,
      amount,
      score,
      stoppedTrading: facts.stopped_trading === true,
    };
  });

  // Guard the divisor: every score can legitimately be 0 on a flat period.
  const top = scored.reduce((max, row) => Math.max(max, row.score), 0);

  return scored
    .sort((a, b) => b.score - a.score)
    .map(({ insight, amount, score, stoppedTrading }) => ({
      insight,
      impact: {
        score,
        amount,
        share: top > 0 ? score / top : 0,
        direction: amount === null || amount === 0 ? 'flat' : amount > 0 ? 'up' : 'down',
        stoppedTrading,
      },
    }));
}

/** Signed rupee label for a finding's bar, e.g. `−₹1,329`. */
export function formatImpact(amount: number | null): string | null {
  if (amount === null || amount === 0) {
    return null;
  }
  const rounded = Math.round(Math.abs(amount));
  const formatted = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 }).format(rounded);
  // A true minus sign rather than a hyphen: these sit in a column of figures.
  return `${amount > 0 ? '+' : '−'}₹${formatted}`;
}
