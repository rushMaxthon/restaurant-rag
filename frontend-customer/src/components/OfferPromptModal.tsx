import { formatCurrency } from '../services/api';
import type { PendingOfferPrompt, PersonalizedOfferCard } from '../types/app';
import { getOfferPalette } from './offers/offerPalette';

interface OfferPromptModalProps {
  visible: boolean;
  prompt: PendingOfferPrompt | null;
  onApply: (offerId: string) => void;
  onContinue: () => void;
  onDismiss: () => void;
}

function renderEndsLabel(expiresAt: string | null) {
  if (!expiresAt) {
    return null;
  }
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
  }).format(new Date(expiresAt));
}

function OfferPromptCard({
  compact,
  offer,
  onApply,
}: {
  compact: boolean;
  offer: PersonalizedOfferCard;
  onApply: (offerId: string) => void;
}) {
  const palette = getOfferPalette({
    offer_type: offer.offer_type,
    audience_type: offer.audience_type,
    cuisine_type: offer.cuisine_type,
    discount_type: offer.discount_type,
  });

  return (
    <article
      className={`offer-prompt-modal__offer-card${compact ? ' offer-prompt-modal__offer-card--compact' : ''}`}
      style={{ backgroundColor: palette.surface }}
    >
      <div
        className="offer-prompt-modal__glow"
        style={{ backgroundColor: palette.glow }}
      />
      <div
        className="offer-prompt-modal__shape offer-prompt-modal__shape--primary"
        style={{ backgroundColor: palette.shapePrimary }}
      />
      <div
        className="offer-prompt-modal__shape offer-prompt-modal__shape--secondary"
        style={{ backgroundColor: palette.shapeSecondary }}
      />

      <div className="offer-prompt-modal__header">
        <span
          className="offer-prompt-modal__badge"
          style={{
            backgroundColor: palette.badgeSurface,
            color: palette.accent,
          }}
        >
          Offer available
        </span>
        <span
          className="offer-prompt-modal__discount"
          style={{ color: palette.accent }}
        >
          {offer.discount_label ?? 'Unlock savings'}
        </span>
      </div>

      <div className="offer-prompt-modal__copy">
        <h2>{offer.title}</h2>
        <p className="offer-prompt-modal__restaurant">{offer.restaurant_name}</p>
        <p className="offer-prompt-modal__subtitle">
          {offer.subtitle || 'This order is eligible for a live restaurant offer.'}
        </p>
      </div>

      <div className="offer-prompt-modal__meta">
        <span className="offer-prompt-modal__chip">
          {Number(offer.minimum_order_amount) > 0
            ? `Min ${formatCurrency(offer.minimum_order_amount)}`
            : 'No min order'}
        </span>
        {offer.expires_at ? (
          <span className="offer-prompt-modal__chip">
            Ends {renderEndsLabel(offer.expires_at)}
          </span>
        ) : null}
      </div>

      <button
        className="primary-button offer-prompt-modal__apply"
        onClick={() => onApply(offer.offer_id)}
        style={{
          background: palette.ctaSurface,
          color: palette.ctaText,
          boxShadow: 'none',
        }}
        type="button"
      >
        Apply offer
      </button>
    </article>
  );
}

export function OfferPromptModal({
  visible,
  prompt,
  onApply,
  onContinue,
  onDismiss,
}: OfferPromptModalProps) {
  if (!visible || !prompt || prompt.offers.length === 0) {
    return null;
  }

  const multipleOffers = prompt.offers.length > 1;

  if (!multipleOffers) {
    const offer = prompt.offers[0];
    const palette = getOfferPalette({
      offer_type: offer.offer_type,
      audience_type: offer.audience_type,
      cuisine_type: offer.cuisine_type,
      discount_type: offer.discount_type,
    });

    return (
      <div aria-modal="true" className="app-modal" role="dialog">
        <button
          aria-label="Close"
          className="app-modal__backdrop"
          onClick={onDismiss}
          type="button"
        />
        <div
          className="app-modal__card offer-prompt-modal"
          style={{ backgroundColor: palette.surface }}
        >
          <div
            className="offer-prompt-modal__glow"
            style={{ backgroundColor: palette.glow }}
          />
          <div
            className="offer-prompt-modal__shape offer-prompt-modal__shape--primary"
            style={{ backgroundColor: palette.shapePrimary }}
          />
          <div
            className="offer-prompt-modal__shape offer-prompt-modal__shape--secondary"
            style={{ backgroundColor: palette.shapeSecondary }}
          />

          <div className="offer-prompt-modal__header">
            <span
              className="offer-prompt-modal__badge"
              style={{
                backgroundColor: palette.badgeSurface,
                color: palette.accent,
              }}
            >
              Offer available
            </span>
            <span
              className="offer-prompt-modal__discount"
              style={{ color: palette.accent }}
            >
              {offer.discount_label ?? 'Unlock savings'}
            </span>
          </div>

          <div className="offer-prompt-modal__copy">
            <h2>{offer.title}</h2>
            <p className="offer-prompt-modal__restaurant">{offer.restaurant_name}</p>
            <p className="offer-prompt-modal__subtitle">
              {offer.subtitle || 'This order is eligible for a live restaurant offer.'}
            </p>
          </div>

          <div className="offer-prompt-modal__meta">
            <span className="offer-prompt-modal__chip">
              {Number(offer.minimum_order_amount) > 0
                ? `Min ${formatCurrency(offer.minimum_order_amount)}`
                : 'No min order'}
            </span>
            {offer.expires_at ? (
              <span className="offer-prompt-modal__chip">
                Ends {renderEndsLabel(offer.expires_at)}
              </span>
            ) : null}
          </div>

          <div className="app-modal__actions offer-prompt-modal__actions">
            <button className="secondary-button" onClick={onContinue} type="button">
              Continue without offer
            </button>
            <button
              className="primary-button"
              onClick={() => onApply(offer.offer_id)}
              style={{
                background: palette.ctaSurface,
                color: palette.ctaText,
                boxShadow: 'none',
              }}
              type="button"
            >
              Apply offer
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div aria-modal="true" className="app-modal" role="dialog">
      <button
        aria-label="Close"
        className="app-modal__backdrop"
        onClick={onDismiss}
        type="button"
      />
      <div className="app-modal__card offer-prompt-modal offer-prompt-modal--multi">
        <div className="offer-prompt-modal__intro">
          <span className="offer-prompt-modal__eyebrow">
            {multipleOffers ? 'Choose your best offer' : 'Offer available'}
          </span>
          <h2 className="offer-prompt-modal__heading">
            {multipleOffers
              ? `${prompt.offers.length} eligible offers for this add`
              : 'Apply this offer before adding to cart'}
          </h2>
        </div>

        {multipleOffers ? (
          <div className="offer-prompt-modal__carousel" role="list">
            {prompt.offers.map((offer) => (
              <div
                className="offer-prompt-modal__carousel-item"
                key={offer.offer_id}
                role="listitem"
              >
                <OfferPromptCard compact offer={offer} onApply={onApply} />
              </div>
            ))}
          </div>
        ) : (
          <OfferPromptCard compact={false} offer={prompt.offers[0]} onApply={onApply} />
        )}

        <div className="app-modal__actions offer-prompt-modal__actions">
          <button className="secondary-button" onClick={onContinue} type="button">
            Continue without offer
          </button>
        </div>
      </div>
    </div>
  );
}
