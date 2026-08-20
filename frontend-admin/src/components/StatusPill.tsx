import type { OrderStatus } from '../types/app';

export type StatusPillTone =
  | 'success'
  | 'warning'
  | 'info'
  | 'primary'
  | 'danger'
  | 'muted';

interface StatusPillProps {
  status: string | OrderStatus;
  className?: string;
}

export function resolveStatusPillTone(status: string | OrderStatus): StatusPillTone {
  const normalized = status.toUpperCase();

  // Payment states resolve first. Falling through to the generic chain below
  // would render an unpaid or cancelled order as a plain grey pill, visually
  // identical to a live one.
  if (normalized === 'PAYMENT_PENDING') {
    return 'warning';
  }
  if (normalized === 'CANCELLED' || normalized === 'FAILED') {
    return 'danger';
  }
  if (normalized === 'PAID' || normalized === 'COD') {
    return 'success';
  }
  if (normalized === 'REFUNDED') {
    return 'info';
  }

  return normalized === 'DELIVERED' ||
    normalized === 'APPROVED' ||
    normalized === 'OPEN' ||
    normalized === 'ACTIVE' ||
    normalized === 'LIVE' ||
    normalized === 'PUBLISHED' ||
    normalized === 'SUCCESS' ||
    normalized === 'AVAILABLE'
    ? 'success'
    : normalized === 'OUT_FOR_DELIVERY'
      ? 'info'
      : normalized === 'PREPARING' ||
          normalized === 'PENDING' ||
          normalized === 'NEW' ||
          normalized === 'DRAFT' ||
          normalized === 'PAUSED' ||
          normalized === 'BESTSELLER' ||
          normalized === 'BEST SELLER' ||
          normalized.startsWith('5 STAR') ||
          normalized.startsWith('4 STAR')
        ? 'warning'
        : normalized === 'ACCEPTED' || normalized === 'ADMIN'
          ? 'primary'
          : normalized === 'PLACED' ||
              normalized === 'CLOSED' ||
              normalized === 'INACTIVE' ||
              normalized === 'ARCHIVED' ||
              normalized === 'HIDDEN'
            ? 'muted'
            : normalized === 'DISABLED'
              ? 'danger'
              : normalized === 'EXPIRED'
                ? 'muted'
                : normalized === 'FAILURE'
                  ? 'danger'
                  : normalized.endsWith('MS')
                    ? 'info'
                    : 'muted';
}

export function StatusPill({ status, className }: StatusPillProps) {
  const tone = resolveStatusPillTone(status);

  return (
    <span className={`status-pill status-pill--${tone}${className ? ` ${className}` : ''}`}>
      {status.replaceAll('_', ' ')}
    </span>
  );
}
