/**
 * "What are you telling them?" — a different editor per channel.
 *
 * The old step 3 was a push editor wearing a generic label: a 65-character
 * title, a 240-character body and a "where does tapping it go" dropdown, shown
 * whatever the owner had picked. Instagram has no title and cannot post
 * without a photo; SMS has no title and is billed by the character; WhatsApp
 * cannot be free-typed at all, because Meta approves the layout in advance.
 * Rendering one form for all six would either lie about what is possible or
 * bury every owner under fields that do not apply to them.
 *
 * So the fields come from `channels.ts`, and this file only decides how to
 * draw them. Adding a channel means adding a row to the registry.
 */

import { BadgePercent, Check, Hash, Image, Link2, Tag } from 'lucide-react';
import { CampaignNotices } from './CampaignNotices';
import { getChannel, messageParts } from './channels';
import { MERGE_FIELDS, findUnknownTokens } from './mergeFields';
import { formatCurrency } from '../../services/api';
import { marketingReference } from '../../services/marketing/marketingApi';
import type {
  CampaignContent,
  CampaignContentExtra,
  CampaignDeepLink,
  MarketingChannel,
  MessageTemplate,
} from '../../services/marketing/types';

interface ContentStepProps {
  channel: MarketingChannel;
  content: CampaignContent;
  templates: MessageTemplate[];
  offerId: string | null;
  /** Worst case if every reachable person redeems. Zero without an offer. */
  exposure: number;
  onContent: (changes: Partial<CampaignContent>) => void;
  onExtra: (changes: Partial<CampaignContentExtra>) => void;
  onOffer: (offerId: string | null) => void;
}

const DEEP_LINKS: Array<{ value: CampaignDeepLink; label: string }> = [
  { value: 'RESTAURANT_HOME', label: 'Your restaurant page' },
  { value: 'MENU_ITEM', label: 'The dish being promoted' },
  { value: 'OFFERS', label: 'The offer' },
  { value: 'CART', label: 'Their cart' },
];

const CTA_LABELS = ['Order now', 'See menu', 'Learn more', 'Call us'];

export function ContentStep({
  channel,
  content,
  templates,
  offerId,
  exposure,
  onContent,
  onExtra,
  onOffer,
}: ContentStepProps) {
  const definition = getChannel(channel);
  const spec = definition.content;
  const isSocial = definition.family === 'SOCIAL';

  const unknownTokens = spec.mergeFields
    ? findUnknownTokens(`${content.title} ${content.body}`)
    : [];
  const titleTooLong = spec.title ? content.title.length > spec.title.limit : false;
  const bodyTooLong = content.body.length > spec.body.limit;
  const parts = messageParts(content.body, spec);

  return (
    <>
      {/* ------------------------------------------------------- offer -- */}
      <div className="mkt-section">
        <span className="mkt-section__label">
          {isSocial ? 'Track it with a code' : 'Attach an offer'}{' '}
          <span>{isSocial ? 'Optional' : 'Optional — news works too'}</span>
        </span>

        {isSocial ? (
          /* A public post writes no recipient rows, so the per-recipient
             attribution the rest of the Hub runs on cannot see it at all. A
             code typed into the cart is the only honest link between a post
             and an order, which is why this replaces the offer picker here
             rather than sitting beside it. */
          <label className="mkt-field">
            <span className="mkt-field__label">
              <Tag size={13} strokeWidth={2.3} />
              Promo code
            </span>
            <input
              maxLength={24}
              onChange={(event) =>
                onExtra({ promo_code: event.target.value.toUpperCase() || null })
              }
              placeholder="INSTA20"
              value={content.extra.promo_code ?? ''}
            />
            <span className="mkt-field__hint">
              Anyone can see a post, so we cannot tell who ordered because of it. A code
              they type at checkout is how this campaign gets credit.
            </span>
          </label>
        ) : (
          <>
            <div className="mkt-grid mkt-grid--3">
              <button
                aria-pressed={offerId === null}
                className={offerId === null ? 'mkt-pick mkt-pick--selected' : 'mkt-pick'}
                onClick={() => onOffer(null)}
                type="button"
              >
                <span aria-hidden="true" className="mkt-pick__tick">
                  <Check size={12} strokeWidth={3.4} />
                </span>
                <span className="mkt-pick__title">No offer</span>
                <span className="mkt-pick__text">
                  Just news — a new dish, a closure, a thank you.
                </span>
              </button>

              {marketingReference.offers.map((entry) => (
                <button
                  aria-pressed={offerId === entry.id}
                  className={offerId === entry.id ? 'mkt-pick mkt-pick--selected' : 'mkt-pick'}
                  key={entry.id}
                  onClick={() => onOffer(entry.id)}
                  type="button"
                >
                  <span aria-hidden="true" className="mkt-pick__tick">
                    <Check size={12} strokeWidth={3.4} />
                  </span>
                  <span className="mkt-pick__row">
                    <span aria-hidden="true" className="mkt-pick__icon">
                      <BadgePercent size={18} strokeWidth={2.1} />
                    </span>
                    <span className="mkt-pick__badge">{entry.discount_label}</span>
                  </span>
                  <span className="mkt-pick__title">{entry.name}</span>
                  <span className="mkt-pick__text">
                    Min {formatCurrency(entry.minimum_order_amount)} · {entry.valid_for_days} days
                    · {entry.applies_to}
                  </span>
                </button>
              ))}
            </div>

            {exposure > 0 ? (
              <p className="mkt-field__hint">
                Worst case, if every reachable customer redeems this:{' '}
                <strong>{formatCurrency(exposure)}</strong> in discount. Your existing
                discount caps still apply.
              </p>
            ) : null}
          </>
        )}
      </div>

      {/* ----------------------------------------------------- message -- */}
      <div className="mkt-section">
        <span className="mkt-section__label">
          {isSocial ? 'Write the post' : `Write the ${definition.noun}`}{' '}
          <span>{spec.templateOnly ? 'Pick an approved layout' : 'Or start from a template'}</span>
        </span>

        {templates.length > 0 ? (
          <label className="mkt-field">
            <span className="mkt-field__label">
              {spec.templateOnly ? 'Approved layout' : 'Template'}
            </span>
            <select
              onChange={(event) => {
                const template = templates.find((entry) => entry.id === event.target.value);
                if (template) {
                  onContent({
                    title: template.title,
                    body: template.body,
                    template_id: template.id,
                  });
                }
              }}
              value={content.template_id ?? ''}
            >
              <option value="">
                {spec.templateOnly ? 'Choose a layout…' : 'Choose a template…'}
              </option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </select>
            {spec.templateOnly ? (
              <span className="mkt-field__hint">
                WhatsApp only delivers layouts Meta has approved in advance. You can change
                the wording in the blanks, not the shape.
              </span>
            ) : null}
          </label>
        ) : null}

        {spec.title ? (
          <label className={titleTooLong ? 'mkt-field mkt-field--invalid' : 'mkt-field'}>
            <span className="mkt-field__label">
              {spec.title.label}
              <span
                className={
                  titleTooLong ? 'mkt-field__count mkt-field__count--over' : 'mkt-field__count'
                }
              >
                {content.title.length}/{spec.title.limit}
              </span>
            </span>
            <input
              onChange={(event) => onContent({ title: event.target.value })}
              placeholder={spec.title.placeholder}
              value={content.title}
            />
            <span className="mkt-field__hint">
              {titleTooLong ? 'This will be cut off where it is shown.' : spec.title.hint}
            </span>
          </label>
        ) : null}

        <label className={bodyTooLong ? 'mkt-field mkt-field--invalid' : 'mkt-field'}>
          <span className="mkt-field__label">
            {spec.body.label}
            <span
              className={
                bodyTooLong ? 'mkt-field__count mkt-field__count--over' : 'mkt-field__count'
              }
            >
              {content.body.length}/{spec.body.limit}
            </span>
          </span>
          <textarea
            onChange={(event) => onContent({ body: event.target.value })}
            placeholder={spec.body.placeholder}
            rows={spec.body.rows}
            value={content.body}
          />
          <span className="mkt-field__hint">{spec.body.hint}</span>
        </label>

        {/* The bill, as it is typed. An owner who writes one more sentence
            and thereby doubles the cost of the send should find that out
            here, not on an invoice. */}
        {spec.segmentLength ? (
          <p
            className={
              parts > 1 ? 'mkt-field__hint mkt-field__hint--warn' : 'mkt-field__hint'
            }
          >
            This is <strong>{parts === 1 ? '1 message' : `${parts} messages`}</strong> per
            person, at about {formatCurrency(spec.perMessageCost)} each. The
            &ldquo;{spec.footer}&rdquo; line is counted too.
          </p>
        ) : null}

        {spec.mergeFields ? (
          <div className="mkt-chips">
            <span className="mkt-field__hint">Insert:</span>
            {MERGE_FIELDS.map((field) => (
              <button
                className="mkt-chip"
                key={field.token}
                onClick={() => onContent({ body: `${content.body}${field.token}` })}
                title={field.hint}
                type="button"
              >
                {field.label}
              </button>
            ))}
          </div>
        ) : null}

        {unknownTokens.length > 0 ? (
          <CampaignNotices
            notices={[
              {
                id: 'unknown-token',
                tone: 'block',
                title: `We cannot fill in ${unknownTokens.join(', ')}`,
                description:
                  'Customers would see it exactly as written. Remove it, or use one of the fields above.',
              },
            ]}
          />
        ) : null}
      </div>

      {/* ------------------------------------------------------- photo -- */}
      {spec.image !== 'none' ? (
        <div className="mkt-section">
          <span className="mkt-section__label">
            Photo <span>{spec.image === 'required' ? 'Required' : 'Optional'}</span>
          </span>
          <label className="mkt-field">
            <span className="mkt-field__label">
              <Image size={13} strokeWidth={2.3} />
              Link to the photo
            </span>
            <input
              onChange={(event) => onExtra({ image_url: event.target.value || null })}
              placeholder="https://…"
              value={content.extra.image_url ?? ''}
            />
            <span className="mkt-field__hint">
              {spec.image === 'required'
                ? 'Instagram will not accept a post without a photo or a video.'
                : 'A photo roughly doubles how many people stop to read a post.'}
            </span>
          </label>
        </div>
      ) : null}

      {/* ---------------------------------------------------- hashtags -- */}
      {spec.hashtags ? (
        <div className="mkt-section">
          <span className="mkt-section__label">
            Hashtags <span>Optional</span>
          </span>
          <label className="mkt-field">
            <span className="mkt-field__label">
              <Hash size={13} strokeWidth={2.3} />
              Tags
            </span>
            <input
              onChange={(event) => onExtra({ hashtags: event.target.value || null })}
              placeholder="#biryani #bangalorefood #indiranagar"
              value={content.extra.hashtags ?? ''}
            />
          </label>
          <label className="mkt-toggle">
            <input
              checked={Boolean(content.extra.hashtags_in_comment)}
              onChange={(event) => onExtra({ hashtags_in_comment: event.target.checked })}
              type="checkbox"
            />
            <span>
              Put them in the first comment instead
              <span className="mkt-field__hint">
                Keeps the caption clean. They still work the same way.
              </span>
            </span>
          </label>
        </div>
      ) : null}

      {/* --------------------------------------------------- where to -- */}
      {spec.deepLink ? (
        <div className="mkt-section">
          <label className="mkt-field">
            <span className="mkt-field__label">
              <Link2 size={13} strokeWidth={2.3} />
              Where does tapping it go?
            </span>
            <select
              onChange={(event) =>
                onContent({ deep_link: event.target.value as CampaignDeepLink })
              }
              value={content.deep_link}
            >
              {DEEP_LINKS.map((link) => (
                <option key={link.value} value={link.value}>
                  {link.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}

      {spec.cta ? (
        <div className="mkt-section">
          <span className="mkt-section__label">
            Button <span>Optional</span>
          </span>
          <div className="mkt-chips">
            {CTA_LABELS.map((label) => (
              <button
                className={
                  content.extra.cta_label === label ? 'mkt-chip mkt-chip--on' : 'mkt-chip'
                }
                key={label}
                onClick={() =>
                  onExtra({ cta_label: content.extra.cta_label === label ? null : label })
                }
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </>
  );
}
