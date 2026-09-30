/**
 * What a public post did, reported as what it can honestly claim.
 *
 * A direct campaign's report reads recipient rows: who it reached, who it
 * failed for, and which of those people then ordered inside their own window.
 * None of that exists here. A post was seen by people this product has no
 * identity for, so this screen answers two narrower questions instead —
 * *where is the post* and *what did the platform say about it* — and says
 * plainly that the orders below are only the ones that typed the code.
 *
 * The understatement is the honest part and is written into the copy. An
 * owner comparing a push campaign's 41 attributed orders against a post's 6
 * is comparing two different measurements, and a report that presented them
 * as the same number would be the most expensive lie in the product.
 */

import { ExternalLink, Eye, Hash, ImageOff, TriangleAlert } from 'lucide-react';
import { formatDate } from '../../services/api';
import { getChannel } from './channels';
import type { MarketingChannel, SocialPost } from '../../services/marketing/types';

interface SocialReportProps {
  channel: MarketingChannel;
  post: SocialPost;
}

/**
 * Meta's metric names, in the owner's words.
 *
 * Anything not in this map is still shown, with its raw name tidied up — a
 * platform adding a metric should not make it invisible, and guessing wrong
 * about what to hide is worse than an ugly label.
 */
const METRIC_LABELS: Record<string, string> = {
  impressions: 'Times shown',
  reach: 'People who saw it',
  likes: 'Likes',
  comments: 'Comments',
  saved: 'Saves',
  post_impressions: 'Times shown',
  post_impressions_unique: 'People who saw it',
  post_engaged_users: 'People who interacted',
  post_clicks: 'Clicks',
};

function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key.replace(/_/g, ' ');
}

export function SocialReport({ channel, post }: SocialReportProps) {
  const definition = getChannel(channel);
  const metrics = Object.entries(post.insights ?? {});

  if (post.state === 'FAILED') {
    return (
      <div className="mkt-empty">
        <span className="mkt-empty__icon">
          <TriangleAlert size={26} strokeWidth={2} />
        </span>
        <strong>This post did not go up</strong>
        <p>{post.reason ?? `${definition.label} refused it.`}</p>
      </div>
    );
  }

  if (post.dry_run) {
    return (
      <div className="mkt-empty">
        <span className="mkt-empty__icon">
          <ImageOff size={26} strokeWidth={2} />
        </span>
        <strong>Nothing was posted</strong>
        <p>
          Sending is switched off in this environment, so the campaign ran end to end
          without {definition.label} ever being called. Everything else here is real.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="mkt-postcard">
        <div className="mkt-postcard__copy">
          <strong>Live on {definition.label}</strong>
          <span>
            {post.published_at ? `Posted ${formatDate(post.published_at)}` : 'Posted'}
          </span>
        </div>
        {post.permalink ? (
          <a
            className="mkt-btn mkt-btn--ghost mkt-btn--sm"
            href={post.permalink}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLink size={14} strokeWidth={2.3} />
            See the post
          </a>
        ) : null}
      </div>

      {metrics.length > 0 ? (
        <ul className="mkt-reach">
          {metrics.map(([key, value]) => (
            <li className="mkt-reach__item" key={key}>
              <span aria-hidden="true" className="mkt-reach__icon">
                <Eye size={14} strokeWidth={2.2} />
              </span>
              <div className="mkt-reach__copy">
                <strong>{metricLabel(key)}</strong>
              </div>
              <strong className="mkt-reach__count">{value.toLocaleString('en-CA')}</strong>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mkt-field__hint">
          {definition.label} has not sent its numbers back yet. They usually appear within
          an hour of posting and keep moving for a few days.
        </p>
      )}

      {post.insights_updated_at ? (
        <p className="mkt-field__hint">
          Numbers from {definition.label}, last checked {formatDate(post.insights_updated_at)}.
        </p>
      ) : null}

      {/* The honest caveat, next to the numbers rather than in a footnote. */}
      <div className="mkt-notice mkt-notice--info">
        <span aria-hidden="true" className="mkt-notice__icon">
          <Hash size={15} strokeWidth={2.3} />
        </span>
        <span className="mkt-notice__copy">
          <strong>
            {post.promo_code
              ? `Orders are counted by the code ${post.promo_code}`
              : 'This post has no code, so no orders can be traced to it'}
          </strong>
          <span>
            {post.promo_code
              ? 'Anyone can see a post, so we cannot tell who ordered because of it. Only people who typed the code at checkout are counted — the real number is higher than what you see below.'
              : 'Add a promo code to the next post and its orders will show up here.'}
          </span>
        </span>
      </div>
    </>
  );
}
