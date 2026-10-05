const ENUM_LABEL_OVERRIDES: Record<string, string> = {
  COD: 'Cash on Delivery',
  CASH_ON_DELIVERY: 'Cash on Delivery',
  ASAP: 'ASAP',
  AI: 'AI',
  AI_GENERATED: 'AI generated',
  GOOGLE_PAY: 'Google Pay',
  UPI: 'UPI',
};

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * "2026-09-21" → "21 Sep", for a chart axis.
 *
 * Read from the string rather than through `Date`: `new Date("2026-01-01")`
 * is midnight UTC, which is still the previous day anywhere west of
 * Greenwich, and a chart whose bars are labelled a day early is wrong in a
 * way nobody reports. Anything that is not a real ISO date is returned as it
 * came, so a label the API already wrote for a person is left alone.
 */
export function shortDay(label: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(label);
  if (!match) {
    return label;
  }
  const month = Number(match[2]);
  const day = Number(match[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) {
    return label;
  }
  return `${day} ${MONTHS[month - 1]}`;
}

/** "1 order" / "3 orders" — count always included. */
export function pluralize(count: number, singular: string, plural?: string): string {
  const label = count === 1 ? singular : (plural ?? `${singular}s`);
  return `${count} ${label}`;
}

/** Turns raw enum-ish values ("cash_on_delivery", "ORDER_PLACED") into friendly labels. */
export function humanizeEnum(value: string | null | undefined): string {
  if (!value) {
    return '';
  }
  const key = value.trim().toUpperCase().replaceAll(' ', '_');
  const override = ENUM_LABEL_OVERRIDES[key];
  if (override) {
    return override;
  }
  return key
    .split('_')
    .filter(Boolean)
    .map((word) => word[0] + word.slice(1).toLowerCase())
    .join(' ');
}

/**
 * Human latency: "748 ms", "14.4 s", "2.1 min".
 * Pass zeroLabel (e.g. "Cached") to special-case exact zeros.
 */
export function formatResponseTime(
  ms: number | null | undefined,
  options?: { zeroLabel?: string },
): string {
  const value = ms ?? 0;
  if (value === 0 && options?.zeroLabel) {
    return options.zeroLabel;
  }
  if (value < 1000) {
    return `${value} ms`;
  }
  if (value < 90000) {
    return `${(value / 1000).toFixed(1)} s`;
  }
  return `${(value / 60000).toFixed(1)} min`;
}
