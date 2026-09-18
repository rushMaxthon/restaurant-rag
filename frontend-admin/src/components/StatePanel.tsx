import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

/**
 * The shell behind every "there is nothing to show" region — whether that is
 * because the data is empty, because a filter excluded it, or because the
 * request failed.
 *
 * One shell rather than three keeps the three cases the same size and shape, so
 * swapping between them does not shift the surrounding layout.
 *
 * The shape itself is `empty-state`, shared with the storefront: a radial wash
 * behind a haloed icon, centred. It replaces a left-aligned dashed box, because
 * an empty screen is an invitation to act and a dashed rectangle reads as a
 * form field nobody filled in.
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
  const isError = tone === 'error';

  return (
    <div
      className={
        isError
          ? 'empty-panel empty-state empty-state--error empty-panel--error'
          : 'empty-panel empty-state'
      }
    >
      <span className="empty-panel__icon empty-state-icon">
        {/* Larger than the 18px it used to be: the icon now sits in a 5.5rem
            disc, and a small glyph in a large halo reads as a mistake. */}
        <Icon size={26} strokeWidth={1.9} />
      </span>
      <strong>{title}</strong>
      <span>{description}</span>
      {action ? <div className="empty-panel__action">{action}</div> : null}
    </div>
  );
}
