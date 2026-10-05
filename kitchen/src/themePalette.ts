import type { OrderStatus } from '@/types/app';

// One colour per order status, the same in light and dark mode: a cook learns
// "blue is new" once, and the board should not teach them a second mapping
// when the tablet switches theme at night.
export const STATUS_COLORS: Record<OrderStatus, string> = {
  PAYMENT_PENDING: '#A1A1AA',
  PLACED: '#2563EB',
  ACCEPTED: '#D97706',
  PREPARING: '#EA580C',
  OUT_FOR_DELIVERY: '#7C3AED',
  DELIVERED: '#16A34A',
  CANCELLED: '#71717A',
};

// WCAG AA for normal text. Ticket labels are read at arm's length across a
// kitchen, so anything weaker is not legible in practice.
export const MIN_TEXT_CONTRAST = 4.5;

const DARK_INK = '#0A0A0A';
const LIGHT_INK = '#FFFFFF';

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

// Text colour for a label sitting on a status chip.
export function inkOn(background: string): string {
  return contrast(background, LIGHT_INK) >= contrast(background, DARK_INK)
    ? LIGHT_INK
    : DARK_INK;
}
