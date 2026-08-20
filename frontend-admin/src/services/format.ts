const ENUM_LABEL_OVERRIDES: Record<string, string> = {
  COD: 'Cash on Delivery',
  CASH_ON_DELIVERY: 'Cash on Delivery',
  ASAP: 'ASAP',
  AI: 'AI',
  AI_GENERATED: 'AI generated',
  GOOGLE_PAY: 'Google Pay',
  UPI: 'UPI',
};

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
