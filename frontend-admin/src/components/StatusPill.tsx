import type { OrderStatus } from '../types/app';
import { formatStatusLabel, resolveStatusPillTone } from './statusPillUtils';

interface StatusPillProps {
  status: string | OrderStatus;
  className?: string;
}

export function StatusPill({ status, className }: StatusPillProps) {
  const tone = resolveStatusPillTone(status);

  return (
    <span className={`status-pill status-pill--${tone}${className ? ` ${className}` : ''}`}>
      {formatStatusLabel(status)}
    </span>
  );
}
