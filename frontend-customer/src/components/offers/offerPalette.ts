import type {
  PersonalizedOfferAudience,
  PersonalizedOfferDiscountType,
  PersonalizedOfferType,
} from '../../types/app';

export interface OfferPalette {
  accent: string;
  surface: string;
  badgeSurface: string;
  glow: string;
  shapePrimary: string;
  shapeSecondary: string;
  ctaSurface: string;
  ctaText: string;
}

interface OfferPaletteInput {
  offer_type: PersonalizedOfferType;
  audience_type?: PersonalizedOfferAudience | null;
  discount_type?: PersonalizedOfferDiscountType | null;
  cuisine_type?: string | null;
}

export function getOfferPalette(offer: OfferPaletteInput): OfferPalette {
  const cuisine = offer.cuisine_type?.toLowerCase() ?? '';
  const audienceType = offer.audience_type ?? null;
  const discountType = offer.discount_type ?? null;
  const isInactive = audienceType === 'INACTIVE_USERS';

  if (discountType === 'FREE_DELIVERY') {
    return {
      accent: '#1A8D83',
      surface: '#DFFAF4',
      badgeSurface: 'rgba(255, 255, 255, 0.5)',
      glow: 'rgba(162, 241, 227, 0.32)',
      shapePrimary: 'rgba(188, 248, 236, 0.44)',
      shapeSecondary: 'rgba(255, 255, 255, 0.64)',
      ctaSurface: '#FFFFFF',
      ctaText: '#176E66',
    };
  }

  if (offer.offer_type === 'WELCOME_FIRST_ORDER') {
    return {
      accent: '#6F57C7',
      surface: '#ECE2FF',
      badgeSurface: 'rgba(255, 255, 255, 0.48)',
      glow: 'rgba(209, 190, 255, 0.34)',
      shapePrimary: 'rgba(226, 212, 255, 0.52)',
      shapeSecondary: 'rgba(255, 255, 255, 0.64)',
      ctaSurface: '#FFFFFF',
      ctaText: '#6448BE',
    };
  }

  if (isInactive) {
    return {
      accent: '#5D52C6',
      surface: '#E9E1FF',
      badgeSurface: 'rgba(255, 255, 255, 0.48)',
      glow: 'rgba(198, 184, 255, 0.34)',
      shapePrimary: 'rgba(219, 207, 255, 0.5)',
      shapeSecondary: 'rgba(255, 255, 255, 0.64)',
      ctaSurface: '#FFFFFF',
      ctaText: '#5B49B8',
    };
  }

  if (cuisine.includes('pizza')) {
    return {
      accent: '#497DD5',
      surface: '#DCEBFF',
      badgeSurface: 'rgba(255, 255, 255, 0.48)',
      glow: 'rgba(171, 204, 255, 0.34)',
      shapePrimary: 'rgba(198, 221, 255, 0.46)',
      shapeSecondary: 'rgba(255, 255, 255, 0.64)',
      ctaSurface: '#FFFFFF',
      ctaText: '#3D6FC3',
    };
  }

  if (cuisine.includes('thai')) {
    return {
      accent: '#1C9E8B',
      surface: '#DFF9F2',
      badgeSurface: 'rgba(255, 255, 255, 0.48)',
      glow: 'rgba(170, 243, 226, 0.32)',
      shapePrimary: 'rgba(193, 248, 235, 0.48)',
      shapeSecondary: 'rgba(255, 255, 255, 0.64)',
      ctaSurface: '#FFFFFF',
      ctaText: '#198675',
    };
  }

  if (
    offer.offer_type === 'COMBO_AFFINITY' ||
    offer.offer_type === 'FAVORITE_ITEM' ||
    offer.offer_type === 'ORDER_HISTORY_MATCH'
  ) {
    return {
      accent: '#4877D0',
      surface: '#DDEAFF',
      badgeSurface: 'rgba(255, 255, 255, 0.48)',
      glow: 'rgba(174, 203, 255, 0.34)',
      shapePrimary: 'rgba(202, 221, 255, 0.46)',
      shapeSecondary: 'rgba(255, 255, 255, 0.64)',
      ctaSurface: '#FFFFFF',
      ctaText: '#3E69BA',
    };
  }

  if (
    offer.offer_type === 'FAVORITE_RESTAURANT' ||
    offer.offer_type === 'BUDGET_BEHAVIOR'
  ) {
    return {
      accent: '#6C58C9',
      surface: '#ECE5FF',
      badgeSurface: 'rgba(255, 255, 255, 0.48)',
      glow: 'rgba(207, 193, 255, 0.34)',
      shapePrimary: 'rgba(226, 213, 255, 0.5)',
      shapeSecondary: 'rgba(255, 255, 255, 0.64)',
      ctaSurface: '#FFFFFF',
      ctaText: '#5D4AB7',
    };
  }

  return {
    accent: '#4A7FD8',
    surface: '#DDEBFF',
    badgeSurface: 'rgba(255, 255, 255, 0.48)',
    glow: 'rgba(174, 205, 255, 0.34)',
    shapePrimary: 'rgba(202, 222, 255, 0.46)',
    shapeSecondary: 'rgba(255, 255, 255, 0.64)',
    ctaSurface: '#FFFFFF',
    ctaText: '#3D70C5',
  };
}
