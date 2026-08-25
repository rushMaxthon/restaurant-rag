import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

/**
 * The shell behind every "there is nothing to show" region — whether that is
 * because the data is empty, because a filter excluded it, or because the
 * request failed.
 *
 * One shell rather than three keeps the three cases the same size and shape, so
 * swapping between them does not shift the surrounding layout.
 */
export type StatePanelTone = 'empty' | 'error';

interface StatePanelProps {
  icon: LucideIcon;
  tone?: StatePanelTone;
  title: string;
  description: string;
  action?: ReactNode;
}

export function StatePanel({
  icon: Icon,
  tone = 'empty',
  title,
  description,
  action,
}: StatePanelProps) {
  return (
    <div className={tone === 'error' ? 'empty-panel empty-panel--error' : 'empty-panel'}>
      <span className="empty-panel__icon">
        <Icon size={18} strokeWidth={2.1} />
      </span>
      <strong>{title}</strong>
      <span>{description}</span>
      {action ? <div className="empty-panel__action">{action}</div> : null}
    </div>
  );
}
