import type { CSSProperties } from 'react';
import { formatCurrency } from '../../services/api';
import type { PersonalizedOfferCard } from '../../types/app';

interface OfferCardProps {
  offer: PersonalizedOfferCard;
  onOpen: (offer: PersonalizedOfferCard) => void;
  disabled?: boolean;
}

interface OfferPalette {
  accentClassName: string;
  style: CSSProperties;
}

function getOfferPalette(offer: PersonalizedOfferCard): OfferPalette {
  const cuisine = offer.cuisine_type?.toLowerCase() ?? '';
  const isInactive = offer.audience_type === 'INACTIVE_USERS';

  if (offer.discount_type === 'FREE_DELIVERY') {
    return {
      accentClassName: 'home-offer-card--teal',
      style: {
        '--offer-bg':
          'radial-gradient(circle at top right, rgba(168, 243, 228, 0.34), transparent 34%), linear-gradient(135deg, #dffaf4 0%, #cbf6ec 54%, #f7fffd 100%)',
        '--offer-border': 'rgba(255, 255, 255, 0.58)',
        '--offer-glow': 'rgba(162, 241, 227, 0.34)',
        '--offer-shape-primary': 'rgba(188, 248, 236, 0.44)',
        '--offer-shape-secondary': 'rgba(255, 255, 255, 0.62)',
        '--offer-badge-bg': 'rgba(255, 255, 255, 0.28)',
        '--offer-accent': '#1A8D83',
        '--offer-cta-bg': '#FFFFFF',
        '--offer-cta-text': '#176E66',
        '--offer-icon-bg': 'rgba(255, 255, 255, 0.28)',
        '--offer-icon-text': '#176E66',
      } as CSSProperties,
    };
  }

  if (offer.offer_type === 'WELCOME_FIRST_ORDER') {
    return {
      accentClassName: 'home-offer-card--orange',
      style: {
        '--offer-bg':
          'radial-gradient(circle at top right, rgba(209, 190, 255, 0.38), transparent 34%), linear-gradient(135deg, #ece2ff 0%, #e3d7ff 54%, #faf7ff 100%)',
        '--offer-border': 'rgba(255, 255, 255, 0.58)',
        '--offer-glow': 'rgba(209, 190, 255, 0.38)',
        '--offer-shape-primary': 'rgba(226, 212, 255, 0.52)',
        '--offer-shape-secondary': 'rgba(255, 255, 255, 0.62)',
        '--offer-badge-bg': 'rgba(255, 255, 255, 0.26)',
        '--offer-accent': '#6F57C7',
        '--offer-cta-bg': '#FFFFFF',
        '--offer-cta-text': '#6448BE',
        '--offer-icon-bg': 'rgba(255, 255, 255, 0.26)',
        '--offer-icon-text': '#6448BE',
      } as CSSProperties,
    };
  }

  if (isInactive) {
    return {
      accentClassName: 'home-offer-card--orange',
      style: {
        '--offer-bg':
          'radial-gradient(circle at top right, rgba(198, 184, 255, 0.36), transparent 34%), linear-gradient(135deg, #e9e1ff 0%, #dfd4ff 54%, #f8f5ff 100%)',
        '--offer-border': 'rgba(255, 255, 255, 0.58)',
        '--offer-glow': 'rgba(198, 184, 255, 0.36)',
        '--offer-shape-primary': 'rgba(219, 207, 255, 0.5)',
        '--offer-shape-secondary': 'rgba(255, 255, 255, 0.62)',
        '--offer-badge-bg': 'rgba(255, 255, 255, 0.26)',
        '--offer-accent': '#5D52C6',
        '--offer-cta-bg': '#FFFFFF',
        '--offer-cta-text': '#5B49B8',
        '--offer-icon-bg': 'rgba(255, 255, 255, 0.28)',
        '--offer-icon-text': '#5B49B8',
      } as CSSProperties,
    };
  }

  if (cuisine.includes('pizza')) {
    return {
      accentClassName: 'home-offer-card--orange',
      style: {
        '--offer-bg':
          'radial-gradient(circle at top right, rgba(171, 204, 255, 0.38), transparent 34%), linear-gradient(135deg, #dcecff 0%, #cfe2ff 54%, #f5f9ff 100%)',
        '--offer-border': 'rgba(255, 255, 255, 0.58)',
        '--offer-glow': 'rgba(171, 204, 255, 0.38)',
        '--offer-shape-primary': 'rgba(198, 221, 255, 0.46)',
        '--offer-shape-secondary': 'rgba(255, 255, 255, 0.62)',
        '--offer-badge-bg': 'rgba(255, 255, 255, 0.28)',
        '--offer-accent': '#497DD5',
        '--offer-cta-bg': '#FFFFFF',
        '--offer-cta-text': '#3D6FC3',
        '--offer-icon-bg': 'rgba(255, 255, 255, 0.3)',
        '--offer-icon-text': '#3D6FC3',
      } as CSSProperties,
    };
  }

  if (cuisine.includes('thai')) {
    return {
      accentClassName: 'home-offer-card--gold',
      style: {
        '--offer-bg':
          'radial-gradient(circle at top right, rgba(170, 243, 226, 0.36), transparent 34%), linear-gradient(135deg, #dff9f2 0%, #d0f5ec 54%, #f7fffd 100%)',
        '--offer-border': 'rgba(255, 255, 255, 0.58)',
        '--offer-glow': 'rgba(170, 243, 226, 0.36)',
        '--offer-shape-primary': 'rgba(193, 248, 235, 0.48)',
        '--offer-shape-secondary': 'rgba(255, 255, 255, 0.62)',
        '--offer-badge-bg': 'rgba(255, 255, 255, 0.28)',
        '--offer-accent': '#1C9E8B',
        '--offer-cta-bg': '#FFFFFF',
        '--offer-cta-text': '#198675',
        '--offer-icon-bg': 'rgba(255, 255, 255, 0.3)',
        '--offer-icon-text': '#198675',
      } as CSSProperties,
    };
  }

  if (
    offer.offer_type === 'COMBO_AFFINITY' ||
    offer.offer_type === 'FAVORITE_ITEM' ||
    offer.offer_type === 'ORDER_HISTORY_MATCH'
  ) {
    return {
      accentClassName: 'home-offer-card--orange',
      style: {
        '--offer-bg':
          'radial-gradient(circle at top right, rgba(174, 203, 255, 0.38), transparent 34%), linear-gradient(135deg, #ddeaff 0%, #cfe1ff 54%, #f6f9ff 100%)',
        '--offer-border': 'rgba(255, 255, 255, 0.58)',
        '--offer-glow': 'rgba(174, 203, 255, 0.38)',
        '--offer-shape-primary': 'rgba(202, 221, 255, 0.46)',
        '--offer-shape-secondary': 'rgba(255, 255, 255, 0.62)',
        '--offer-badge-bg': 'rgba(255, 255, 255, 0.28)',
        '--offer-accent': '#4877D0',
        '--offer-cta-bg': '#FFFFFF',
        '--offer-cta-text': '#3E69BA',
        '--offer-icon-bg': 'rgba(255, 255, 255, 0.3)',
        '--offer-icon-text': '#3E69BA',
      } as CSSProperties,
    };
  }

  if (
    offer.offer_type === 'FAVORITE_RESTAURANT' ||
    offer.offer_type === 'BUDGET_BEHAVIOR'
  ) {
    return {
      accentClassName: 'home-offer-card--orange',
      style: {
        '--offer-bg':
          'radial-gradient(circle at top right, rgba(207, 193, 255, 0.36), transparent 34%), linear-gradient(135deg, #ece5ff 0%, #e2d8ff 54%, #f9f7ff 100%)',
        '--offer-border': 'rgba(255, 255, 255, 0.58)',
        '--offer-glow': 'rgba(207, 193, 255, 0.36)',
        '--offer-shape-primary': 'rgba(226, 213, 255, 0.5)',
        '--offer-shape-secondary': 'rgba(255, 255, 255, 0.62)',
        '--offer-badge-bg': 'rgba(255, 255, 255, 0.26)',
        '--offer-accent': '#6C58C9',
        '--offer-cta-bg': '#FFFFFF',
        '--offer-cta-text': '#5D4AB7',
        '--offer-icon-bg': 'rgba(255, 255, 255, 0.28)',
        '--offer-icon-text': '#5D4AB7',
      } as CSSProperties,
    };
  }

  return {
    accentClassName: 'home-offer-card--orange',
    style: {
      '--offer-bg':
        'radial-gradient(circle at top right, rgba(174, 205, 255, 0.38), transparent 34%), linear-gradient(135deg, #ddeaff 0%, #d0e2ff 54%, #f6f9ff 100%)',
      '--offer-border': 'rgba(255, 255, 255, 0.58)',
      '--offer-glow': 'rgba(174, 205, 255, 0.38)',
      '--offer-shape-primary': 'rgba(202, 222, 255, 0.46)',
      '--offer-shape-secondary': 'rgba(255, 255, 255, 0.62)',
      '--offer-badge-bg': 'rgba(255, 255, 255, 0.28)',
      '--offer-accent': '#4A7FD8',
      '--offer-cta-bg': '#FFFFFF',
      '--offer-cta-text': '#3D70C5',
      '--offer-icon-bg': 'rgba(255, 255, 255, 0.3)',
      '--offer-icon-text': '#3D70C5',
    } as CSSProperties,
  };
}

export function OfferCard({
  offer,
  onOpen,
  disabled = false,
}: OfferCardProps) {
  const palette = getOfferPalette(offer);
  const iconLabel = offer.discount_type === 'FREE_DELIVERY' ? '🚚' : offer.discount_type === 'FLAT' ? '₹' : '%';
  const headline = offer.discount_label ?? offer.badge;
  const metaLabel = offer.minimum_order_amount && Number(offer.minimum_order_amount) > 0
    ? `Min ${formatCurrency(offer.minimum_order_amount)}`
    : offer.expires_at
      ? `Valid till ${new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short' }).format(new Date(offer.expires_at))}`
      : offer.restaurant_name;
  const supportingLabel =
    metaLabel === offer.restaurant_name
      ? offer.subtitle ?? null
      : metaLabel;

  return (
    <button
      className={
        disabled
          ? `home-offer-card ${palette.accentClassName} home-offer-card--disabled`
          : `home-offer-card ${palette.accentClassName}`
      }
      disabled={disabled}
      onClick={() => onOpen(offer)}
      style={palette.style}
      type="button"
    >
      <span className="home-offer-card__glow" aria-hidden="true" />
      <span className="home-offer-card__shape home-offer-card__shape--one" aria-hidden="true" />
      <span className="home-offer-card__shape home-offer-card__shape--two" aria-hidden="true" />
      <div className="home-offer-card__top">
        <div className="home-offer-card__badge">{headline}</div>
        <div className="home-offer-card__icon" aria-hidden="true">
          <span>{iconLabel}</span>
        </div>
      </div>
      <div className="home-offer-card__copy">
        <strong>{offer.title}</strong>
        <p>{offer.restaurant_name}</p>
      </div>
      <div className="home-offer-card__footer">
        <span className="home-offer-card__cta">
          {offer.cta_label}
          <span aria-hidden="true">→</span>
        </span>
        {supportingLabel ? (
          <span className="home-offer-card__supporting-chip">{supportingLabel}</span>
        ) : null}
      </div>
    </button>
  );
}
