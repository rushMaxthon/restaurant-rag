import { plural, translate } from '@/i18n/translate';
import { rupees } from './format';

/** The Earnings screen's period switch: what the server is asked for, and how the hero is labelled. */

export type PeriodKey = 'today' | 'week' | 'month';

export type Period = {
  key: PeriodKey;
  label: string;
  heroLabel: string;
  days: number;
};

/**
 * The labels are getters, read at render: a module constant built once would
 * keep whatever language was in force when the file first loaded.
 */
export const PERIODS: readonly Period[] = [
  {
    key: 'today',
    get label() {
      return translate('money.periodToday');
    },
    get heroLabel() {
      return translate('money.heroToday');
    },
    days: 1,
  },
  {
    key: 'week',
    get label() {
      return translate('money.period7');
    },
    get heroLabel() {
      return translate('money.heroWeek');
    },
    days: 7,
  },
  {
    key: 'month',
    get label() {
      return translate('money.period30');
    },
    get heroLabel() {
      return translate('money.heroMonth');
    },
    days: 30,
  },
];

export function periodFor(key: PeriodKey): Period {
  return PERIODS.find(p => p.key === key) ?? PERIODS[1]!;
}

/** One bar is not a chart. */
export function showsChart(key: PeriodKey): boolean {
  return periodFor(key).days > 1;
}

/**
 * The one line under the hero total. The average is whole rupees: it is a
 * feel for the period, and the exact amounts are on every delivery.
 */
export function heroLine(trips: number, total: string | number): string {
  if (trips <= 0) return translate('money.noDeliveriesYet');
  if (trips === 1) return plural('common.deliveries', 1);
  return translate('money.heroEach', {
    deliveries: plural('common.deliveries', trips),
    amount: rupees(Math.round(Number(total) / trips)),
  });
}
