/**
 * "Ready?" — the last screen, written as a sentence rather than a table.
 *
 * The old step 5 ended in a definition list: Goal, Audience, Branches,
 * Channels, Offer, When. Every row was accurate and the whole thing was
 * unreadable — a schema dump at the exact moment an owner needs to understand
 * one irreversible thing. So the facts are the same facts, assembled into the
 * two or three sentences someone would say out loud before pressing the
 * button, with the number of people and the money in bold.
 *
 * The campaign's name is asked for here rather than at the start. It is
 * filing, not intent: at the beginning it is a blank box in the way, and at
 * the end it writes itself from what was chosen.
 */

import { AlertTriangle, PencilLine } from 'lucide-react';
import { formatCurrency, formatDate } from '../../services/api';
import { pluralize } from '../../services/format';
import { getChannel, estimateSpend } from './channels';
import type {
  CampaignDraft,
  MarketingOffer,
  MarketingSegment,
} from '../../services/marketing/types';

interface ReviewStepProps {
  draft: CampaignDraft;
  segment: MarketingSegment;
  /** People this will actually reach on the chosen channel. */
  reachable: number;
  branchSummary: string;
  offer: MarketingOffer | null;
  /** Worst-case discount if everyone reachable redeems. */
  exposure: number;
  /** What the report will lead with, said once more before the button. */
  successMetric: string;
  name: string;
  onName: (name: string) => void;
  /** Jumps back to a step so a fact in the sentence can be corrected. */
  onEdit: (step: number) => void;
}

export function ReviewStep({
  draft,
  segment,
  reachable,
  branchSummary,
  offer,
  exposure,
  successMetric,
  name,
  onName,
  onEdit,
}: ReviewStepProps) {
  const definition = getChannel(draft.channel);
  const isSocial = definition.family === 'SOCIAL';
  const spend = estimateSpend(definition, reachable, draft.content.body);
  const boost = draft.content.extra.boost_budget ?? 0;

  const when =
    draft.schedule.mode === 'NOW'
      ? isSocial
        ? 'as soon as you confirm'
        : 'immediately, as soon as you confirm'
      : draft.schedule.send_at
        ? `on ${formatDate(draft.schedule.send_at)}`
        : 'at a time you have not chosen yet';

  return (
    <>
      <div className="mkt-verdict">
        {isSocial ? (
          <p className="mkt-verdict__lead">
            You are about to put a <strong>{definition.label} post</strong> in front of{' '}
            <strong>everyone who follows you</strong>
            {boost > 0 ? (
              <>
                , and pay <strong>{formatCurrency(boost)}</strong> to show it to people
                nearby who do not
              </>
            ) : null}
            . It goes out {when}.
          </p>
        ) : (
          <p className="mkt-verdict__lead">
            You are about to send one <strong>{definition.noun}</strong> to{' '}
            <strong>{pluralize(reachable, 'person', 'people')}</strong> — {segment.name} at{' '}
            {branchSummary}. It goes out {when}.
          </p>
        )}

        <p className="mkt-verdict__quote">
          They see: &ldquo;{draft.content.title || draft.content.body.slice(0, 60)}&rdquo;
        </p>

        {spend > 0 ? (
          <p className="mkt-verdict__line">
            Sending it costs about <strong>{formatCurrency(spend)}</strong>.
          </p>
        ) : null}

        {offer ? (
          <p className="mkt-verdict__line">
            If every one of them redeems <strong>{offer.name}</strong>, that is up to{' '}
            <strong>{formatCurrency(exposure)}</strong> in discount.
          </p>
        ) : null}

        <p className="mkt-verdict__line mkt-verdict__line--warn">
          <AlertTriangle size={14} strokeWidth={2.4} />
          {draft.schedule.mode === 'NOW'
            ? 'Once it starts it cannot be recalled.'
            : 'You can cancel any time before it starts.'}
        </p>

        <div className="mkt-verdict__edits">
          <button className="mkt-chip" onClick={() => onEdit(1)} type="button">
            <PencilLine size={12} strokeWidth={2.4} />
            Change where
          </button>
          <button className="mkt-chip" onClick={() => onEdit(3)} type="button">
            <PencilLine size={12} strokeWidth={2.4} />
            Change who
          </button>
          <button className="mkt-chip" onClick={() => onEdit(4)} type="button">
            <PencilLine size={12} strokeWidth={2.4} />
            Change the words
          </button>
          <button className="mkt-chip" onClick={() => onEdit(5)} type="button">
            <PencilLine size={12} strokeWidth={2.4} />
            Change when
          </button>
        </div>
      </div>

      <div className="mkt-section">
        <span className="mkt-section__label">
          Name it so you can find it later <span>Only you see this</span>
        </span>
        <label className="mkt-field">
          <input
            maxLength={80}
            onChange={(event) => onName(event.target.value)}
            placeholder="September winback — Indiranagar"
            value={name}
          />
          {/* The success metric is what the report will lead with, so it is
              said once more here, before the button rather than after. */}
          <span className="mkt-field__hint">
            This campaign will be judged on: <strong>{successMetric}</strong>.
          </span>
        </label>
      </div>
    </>
  );
}
