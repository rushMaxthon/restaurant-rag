/**
 * The campaign as it will actually appear, wherever it is going.
 *
 * One component per channel rather than one configurable box, because the
 * thing an owner is judging is not the text — it is whether the text *fits*.
 * A 240-character push body reads fine in a textarea and is three truncated
 * lines on a lock screen; an Instagram caption is cut at two lines behind a
 * "more"; an SMS silently becomes three billed messages. None of that is
 * visible unless the preview is shaped like the destination.
 *
 * Every preview resolves merge fields through the same `mergeFields` module as
 * the send path, and the recipient switcher always ends on someone with no
 * first name on file — the case nobody thinks to check.
 */

import { useState } from 'react';
import { ChevronLeft, ChevronRight, Heart, Image, MessageCircle, Send, ThumbsUp } from 'lucide-react';
import { PushPreview } from './PushPreview';
import { getChannel, messageParts } from './channels';
import {
  buildPreviewRecipients,
  resolveMergeFields,
  type MergeContext,
} from './mergeFields';
import type { CampaignContent, MarketingChannel } from '../../services/marketing/types';

interface ChannelPreviewProps {
  channel: MarketingChannel;
  content: CampaignContent;
  /** The sender, as the destination shows it: app name or page handle. */
  appName: string;
  branchName: string | null;
  /** Hides the recipient stepper where only one rendering matters. */
  showRecipientSwitcher?: boolean;
}

/**
 * The recipient stepper, shared by every DIRECT preview.
 *
 * Lifted out of `PushPreview` rather than duplicated: the fallback rendering
 * is the reason the switcher exists, and a channel that quietly dropped it
 * would be the channel that ships "Hi there" to nobody's satisfaction.
 */
function RecipientSwitcher({
  index,
  count,
  note,
  onChange,
}: {
  index: number;
  count: number;
  note: string;
  onChange: (next: number) => void;
}) {
  return (
    <div className="mkt-preview__switcher">
      <button
        aria-label="Previous sample recipient"
        className="mkt-preview__step"
        disabled={index === 0}
        onClick={() => onChange(Math.max(index - 1, 0))}
        type="button"
      >
        <ChevronLeft size={15} strokeWidth={2.3} />
      </button>
      <span className="mkt-preview__note">{note}</span>
      <button
        aria-label="Next sample recipient"
        className="mkt-preview__step"
        disabled={index >= count - 1}
        onClick={() => onChange(Math.min(index + 1, count - 1))}
        type="button"
      >
        <ChevronRight size={15} strokeWidth={2.3} />
      </button>
    </div>
  );
}

/** Shared plumbing: pick a sample recipient and resolve the copy against it. */
function useResolved(content: CampaignContent, branchName: string | null) {
  const recipients = buildPreviewRecipients(branchName);
  const [index, setIndex] = useState(0);
  const recipient = recipients[Math.min(index, recipients.length - 1)];
  const context: MergeContext = recipient;
  return {
    recipients,
    recipient,
    index,
    setIndex,
    title: resolveMergeFields(content.title, context),
    body: resolveMergeFields(content.body, context),
  };
}

/* ------------------------------------------------------------------ SMS -- */

function SmsPreview({ content, appName, branchName, showRecipientSwitcher }: Omit<ChannelPreviewProps, 'channel'>) {
  const spec = getChannel('SMS').content;
  const { body, recipient, recipients, index, setIndex } = useResolved(content, branchName);
  const footer = spec.footer ?? '';
  const parts = messageParts(content.body, spec);

  return (
    <div className="mkt-preview">
      <div className="mkt-preview__device">
        <div className="mkt-preview__screen mkt-preview__screen--sms">
          <span className="mkt-preview__sender">{appName}</span>
          <article className="mkt-bubble mkt-bubble--sms" key={body}>
            <p>{body || 'Your text appears here.'}</p>
            {/* Shown greyed and uneditable because the operator appends it
                either way, and it is counted in the length that is billed. */}
            <p className="mkt-bubble__footer">{footer}</p>
          </article>
        </div>
      </div>
      <p className="mkt-preview__meta">
        {parts === 1 ? '1 message' : `${parts} messages`} per person · the opt-out line is
        counted
      </p>
      {showRecipientSwitcher === false ? null : (
        <RecipientSwitcher
          count={recipients.length}
          index={index}
          note={recipient.note}
          onChange={setIndex}
        />
      )}
    </div>
  );
}

/* ------------------------------------------------------------- WhatsApp -- */

function WhatsAppPreview({ content, appName, branchName, showRecipientSwitcher }: Omit<ChannelPreviewProps, 'channel'>) {
  const spec = getChannel('WHATSAPP').content;
  const { title, body, recipient, recipients, index, setIndex } = useResolved(content, branchName);

  return (
    <div className="mkt-preview">
      <div className="mkt-preview__device">
        <div className="mkt-preview__screen mkt-preview__screen--whatsapp">
          <span className="mkt-preview__sender">
            <MessageCircle size={11} strokeWidth={2.6} />
            {appName}
          </span>
          <article className="mkt-bubble mkt-bubble--whatsapp" key={`${title}|${body}`}>
            {content.extra.image_url ? (
              <span className="mkt-bubble__image">
                <Image size={18} strokeWidth={2} />
              </span>
            ) : null}
            {title ? <strong>{title}</strong> : null}
            <p>{body || 'Your message appears here.'}</p>
            {spec.footer ? <p className="mkt-bubble__footer">{spec.footer}</p> : null}
            <span className="mkt-bubble__time">
              {new Date().toLocaleTimeString('en-CA', { hour: 'numeric', minute: '2-digit' })}
            </span>
          </article>
        </div>
      </div>
      {showRecipientSwitcher === false ? null : (
        <RecipientSwitcher
          count={recipients.length}
          index={index}
          note={recipient.note}
          onChange={setIndex}
        />
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- email -- */

function EmailPreview({ content, appName, branchName, showRecipientSwitcher }: Omit<ChannelPreviewProps, 'channel'>) {
  const { title, body, recipient, recipients, index, setIndex } = useResolved(content, branchName);

  return (
    <div className="mkt-preview">
      <div className="mkt-mail">
        <div className="mkt-mail__head">
          <span className="mkt-mail__from">{appName}</span>
          <strong className="mkt-mail__subject">{title || 'Your subject line appears here'}</strong>
        </div>
        {content.extra.image_url ? (
          <span className="mkt-mail__image">
            <Image size={20} strokeWidth={2} />
          </span>
        ) : null}
        <p className="mkt-mail__body">{body || 'Your email appears here.'}</p>
        <p className="mkt-mail__footer">Unsubscribe</p>
      </div>
      {showRecipientSwitcher === false ? null : (
        <RecipientSwitcher
          count={recipients.length}
          index={index}
          note={recipient.note}
          onChange={setIndex}
        />
      )}
    </div>
  );
}

/* --------------------------------------------------------------- social -- */

/**
 * Instagram and Facebook, drawn from the same card.
 *
 * No recipient switcher and no merge fields: a public post has one rendering,
 * seen by everyone. Showing a "sample recipient" here would teach the owner
 * something false about how the post works.
 */
function SocialPreview({
  content,
  appName,
  network,
}: {
  content: CampaignContent;
  appName: string;
  network: 'INSTAGRAM' | 'FACEBOOK';
}) {
  const isInstagram = network === 'INSTAGRAM';
  const caption = content.body;
  const hashtags = (content.extra.hashtags ?? '').trim();
  const inComment = Boolean(content.extra.hashtags_in_comment);

  return (
    <div className="mkt-preview">
      <article className={`mkt-social mkt-social--${network.toLowerCase()}`}>
        <header className="mkt-social__head">
          <span className="mkt-social__avatar" aria-hidden="true" />
          <span className="mkt-social__handle">{appName}</span>
        </header>

        <div className="mkt-social__media">
          {content.extra.image_url ? (
            <img alt="" className="mkt-social__photo" src={content.extra.image_url} />
          ) : (
            <span className="mkt-social__placeholder">
              <Image size={24} strokeWidth={1.8} />
              {isInstagram ? 'A photo is required' : 'Add a photo (optional)'}
            </span>
          )}
        </div>

        <div className="mkt-social__actions" aria-hidden="true">
          {isInstagram ? (
            <>
              <Heart size={16} strokeWidth={2} />
              <MessageCircle size={16} strokeWidth={2} />
              <Send size={16} strokeWidth={2} />
            </>
          ) : (
            <>
              <ThumbsUp size={16} strokeWidth={2} />
              <MessageCircle size={16} strokeWidth={2} />
            </>
          )}
        </div>

        <p className="mkt-social__caption">
          <strong>{appName}</strong>{' '}
          {caption || (isInstagram ? 'Your caption appears here.' : 'Your post appears here.')}
          {hashtags && !inComment ? <span className="mkt-social__tags"> {hashtags}</span> : null}
        </p>

        {hashtags && inComment ? (
          <p className="mkt-social__comment">
            <strong>{appName}</strong> <span className="mkt-social__tags">{hashtags}</span>
          </p>
        ) : null}

        {content.extra.promo_code ? (
          <p className="mkt-social__meta">
            Tracked with code <strong>{content.extra.promo_code}</strong>
          </p>
        ) : null}
      </article>
      <p className="mkt-preview__meta">
        {/* The truncation rule is the one thing an owner cannot see coming. */}
        {isInstagram
          ? 'Instagram shows the first two lines, then "more".'
          : 'Facebook hides anything past about 80 characters behind "See more".'}
      </p>
    </div>
  );
}

/* ----------------------------------------------------------------- root -- */

export function ChannelPreview({
  channel,
  content,
  appName,
  branchName,
  showRecipientSwitcher = true,
}: ChannelPreviewProps) {
  switch (channel) {
    case 'SMS':
      return (
        <SmsPreview
          appName={appName}
          branchName={branchName}
          content={content}
          showRecipientSwitcher={showRecipientSwitcher}
        />
      );
    case 'WHATSAPP':
      return (
        <WhatsAppPreview
          appName={appName}
          branchName={branchName}
          content={content}
          showRecipientSwitcher={showRecipientSwitcher}
        />
      );
    case 'EMAIL':
      return (
        <EmailPreview
          appName={appName}
          branchName={branchName}
          content={content}
          showRecipientSwitcher={showRecipientSwitcher}
        />
      );
    case 'INSTAGRAM':
    case 'FACEBOOK':
      return <SocialPreview appName={appName} content={content} network={channel} />;
    case 'PUSH':
    default:
      return (
        <PushPreview
          appName={appName}
          body={content.body}
          branchName={branchName}
          showRecipientSwitcher={showRecipientSwitcher}
          title={content.title}
        />
      );
  }
}
