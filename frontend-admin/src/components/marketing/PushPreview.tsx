import { useState } from 'react';
import { Bell, ChevronLeft, ChevronRight } from 'lucide-react';
import {
  buildPreviewRecipients,
  resolveMergeFields,
  type PreviewRecipient,
} from './mergeFields';

interface PushPreviewProps {
  title: string;
  body: string;
  /** Shown as the notification's sender, the way a phone shows the app name. */
  appName: string;
  branchName: string | null;
  /** Hides the recipient stepper where only one rendering matters. */
  showRecipientSwitcher?: boolean;
}

function clockLabel(): string {
  return new Date().toLocaleTimeString('en-CA', {
    hour: 'numeric',
    minute: '2-digit',
  });
}

/**
 * The notification as it lands on a lock screen.
 *
 * Deliberately device-shaped rather than a text box: an owner judges length by
 * eye, and a 240-character body that looks fine in a textarea is three
 * truncated lines on a phone. The recipient switcher exists so the fallback
 * rendering — a customer with no first name on file — is seen before sending
 * rather than after.
 */
export function PushPreview({
  title,
  body,
  appName,
  branchName,
  showRecipientSwitcher = true,
}: PushPreviewProps) {
  const recipients: PreviewRecipient[] = buildPreviewRecipients(branchName);
  const [index, setIndex] = useState(0);
  const recipient = recipients[Math.min(index, recipients.length - 1)];

  const resolvedTitle = resolveMergeFields(title, recipient);
  const resolvedBody = resolveMergeFields(body, recipient);

  return (
    <div className="mkt-preview">
      <div className="mkt-preview__device">
        <div className="mkt-preview__screen">
          <div className="mkt-preview__clock">
            <strong>{clockLabel()}</strong>
            <span>
              {new Date().toLocaleDateString('en-CA', {
                weekday: 'long',
                day: 'numeric',
                month: 'long',
              })}
            </span>
          </div>

          <article
            className="mkt-preview__notification"
            /* Re-keyed on the copy so the arrival animation replays as the
               owner types — the message feels like it is landing. */
            key={`${resolvedTitle}|${resolvedBody}`}
          >
            <span className="mkt-preview__app">
              <Bell size={10} strokeWidth={2.6} />
              {appName}
            </span>
            <strong className="mkt-preview__title">
              {resolvedTitle || 'Your title appears here'}
            </strong>
            <p className="mkt-preview__body">
              {resolvedBody || 'Your message appears here.'}
            </p>
          </article>
        </div>
      </div>

      {showRecipientSwitcher ? (
        <div className="mkt-preview__switcher">
          <button
            aria-label="Previous sample recipient"
            className="mkt-preview__step"
            disabled={index === 0}
            onClick={() => setIndex((current) => Math.max(current - 1, 0))}
            type="button"
          >
            <ChevronLeft size={15} strokeWidth={2.3} />
          </button>
          <span className="mkt-preview__note">{recipient.note}</span>
          <button
            aria-label="Next sample recipient"
            className="mkt-preview__step"
            disabled={index >= recipients.length - 1}
            onClick={() =>
              setIndex((current) => Math.min(current + 1, recipients.length - 1))
            }
            type="button"
          >
            <ChevronRight size={15} strokeWidth={2.3} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
