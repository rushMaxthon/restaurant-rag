import { AlertTriangle, RotateCw } from 'lucide-react';
import { StatePanel } from './StatePanel';

interface ErrorPanelProps {
  /** What failed, in the user's terms — "Orders", "This restaurant's menu". */
  title?: string;
  /** The message from the failure. Falls back to something honest but vague. */
  description?: string | null;
  onRetry?: () => void;
  retrying?: boolean;
}

/**
 * What a data region shows when its request failed.
 *
 * Previously a failure fired a toast and then left an empty table behind, which
 * is indistinguishable from "there is no data" — and the toast was gone within
 * seconds, so there was nothing left to act on. This stays on screen and offers
 * the one action that helps.
 */
export function ErrorPanel({
  title = "That didn't load",
  description,
  onRetry,
  retrying = false,
}: ErrorPanelProps) {
  return (
    <StatePanel
      action={
        onRetry ? (
          <button
            className="secondary-button"
            disabled={retrying}
            onClick={onRetry}
            type="button"
          >
            <RotateCw size={14} strokeWidth={2.2} />
            {retrying ? 'Retrying…' : 'Try again'}
          </button>
        ) : undefined
      }
      description={description || 'The request did not complete. This is usually temporary.'}
      icon={AlertTriangle}
      title={title}
      tone="error"
    />
  );
}
