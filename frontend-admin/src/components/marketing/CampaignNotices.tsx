import { Ban, Info, TriangleAlert } from 'lucide-react';
import type { CampaignNotice, NoticeTone } from '../../services/marketing/types';

interface CampaignNoticesProps {
  notices: CampaignNotice[];
  /** Suppresses the info-level ones where space is tight. */
  hideInfo?: boolean;
  /** Makes each notice a button — used on the home screen's attention list. */
  onSelect?: (notice: CampaignNotice) => void;
}

const TONE_ICON = {
  block: Ban,
  warn: TriangleAlert,
  info: Info,
} as const;

const TONE_ORDER: Record<NoticeTone, number> = { block: 0, warn: 1, info: 2 };

/**
 * The safety rail above the send button.
 *
 * Blocks come first and read as refusals; warnings are things the owner may
 * knowingly accept; info is the quiet arithmetic — who was skipped and why —
 * that should be visible but never alarming. Sorting by severity means the one
 * thing stopping the send is always the first thing read.
 *
 * These mirror checks the backend re-runs at send time. The UI showing them is
 * a courtesy, not the enforcement.
 */
export function CampaignNotices({
  notices,
  hideInfo = false,
  onSelect,
}: CampaignNoticesProps) {
  const visible = notices
    .filter((notice) => (hideInfo ? notice.tone !== 'info' : true))
    .slice()
    .sort((a, b) => TONE_ORDER[a.tone] - TONE_ORDER[b.tone]);

  if (visible.length === 0) {
    return null;
  }

  return (
    <ul className="mkt-notices">
      {visible.map((notice) => {
        const Icon = TONE_ICON[notice.tone];
        const body = (
          <>
            <span aria-hidden="true" className="mkt-notice__icon">
              <Icon size={15} strokeWidth={2.3} />
            </span>
            <span className="mkt-notice__copy">
              <strong>{notice.title}</strong>
              <span>{notice.description}</span>
            </span>
          </>
        );

        return (
          <li key={notice.id}>
            {onSelect ? (
              <button
                className={`mkt-notice mkt-notice--${notice.tone} mkt-notice--action`}
                onClick={() => onSelect(notice)}
                type="button"
              >
                {body}
              </button>
            ) : (
              <div className={`mkt-notice mkt-notice--${notice.tone}`}>{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
