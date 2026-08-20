import type {
  PersonalizedOfferAudience,
  PersonalizedOfferCard,
  PersonalizedOfferDiscountType,
  PersonalizedOfferType,
} from '@/types/app';

export interface OfferPalette {
  accent: string;
  surface: string;
  badgeSurface: string;
  glow: string;
  shapePrimary: string;
  shapeSecondary: string;
  ctaSurface: string;
  ctaText: string;
  iconSurface: string;
  iconText: string;
}

type OfferPaletteMode = 'light' | 'dark';

interface OfferPaletteInput {
  offer_type: PersonalizedOfferType;
  audience_type?: PersonalizedOfferAudience | null;
  discount_type?: PersonalizedOfferDiscountType | null;
  discountType?: PersonalizedOfferDiscountType | null;
  cuisine_type?: string | null;
}

function toDarkPalette(palette: OfferPalette): OfferPalette {
  return {
    ...palette,
    surface: 'rgba(28, 34, 44, 0.96)',
    badgeSurface: 'rgba(255, 255, 255, 0.08)',
    glow: 'rgba(255, 255, 255, 0.05)',
    shapePrimary: 'rgba(255, 255, 255, 0.04)',
    shapeSecondary: 'rgba(255, 255, 255, 0.06)',
    ctaSurface: 'rgba(255, 255, 255, 0.08)',
    iconSurface: 'rgba(255, 255, 255, 0.08)',
  };
}

export function getOfferPalette(
  offer: OfferPaletteInput,
  mode: OfferPaletteMode = 'light',
): OfferPalette {
  const cuisine = offer.cuisine_type?.toLowerCase() ?? '';
  const audienceType = offer.audience_type ?? null;
  const discountType = offer.discount_type ?? offer.discountType ?? null;
  const isInactive = audienceType === 'INACTIVE_USERS';

  if (discountType === 'FREE_DELIVERY') {
    const palette = {
      accent: '#1A8D83',
      surface: '#DFFAF4',
      badgeSurface: 'rgba(255, 255, 255, 0.28)',
      glow: 'rgba(162, 241, 227, 0.34)',
      shapePrimary: 'rgba(188, 248, 236, 0.44)',
      shapeSecondary: 'rgba(255, 255, 255, 0.62)',
      ctaSurface: '#FFFFFF',
      ctaText: '#176E66',
      iconSurface: 'rgba(255, 255, 255, 0.28)',
      iconText: '#176E66',
    };
    return mode === 'dark' ? toDarkPalette(palette) : palette;
  }

  if (offer.offer_type === 'WELCOME_FIRST_ORDER') {
    const palette = {
      accent: '#6F57C7',
      surface: '#ECE2FF',
      badgeSurface: 'rgba(255, 255, 255, 0.26)',
      glow: 'rgba(209, 190, 255, 0.38)',
      shapePrimary: 'rgba(226, 212, 255, 0.52)',
      shapeSecondary: 'rgba(255, 255, 255, 0.62)',
      ctaSurface: '#FFFFFF',
      ctaText: '#6448BE',
      iconSurface: 'rgba(255, 255, 255, 0.26)',
      iconText: '#6448BE',
    };
    return mode === 'dark' ? toDarkPalette(palette) : palette;
  }

  if (isInactive) {
    const palette = {
      accent: '#5D52C6',
      surface: '#E9E1FF',
      badgeSurface: 'rgba(255, 255, 255, 0.26)',
      glow: 'rgba(198, 184, 255, 0.36)',
      shapePrimary: 'rgba(219, 207, 255, 0.5)',
      shapeSecondary: 'rgba(255, 255, 255, 0.62)',
      ctaSurface: '#FFFFFF',
      ctaText: '#5B49B8',
      iconSurface: 'rgba(255, 255, 255, 0.28)',
      iconText: '#5B49B8',
    };
    return mode === 'dark' ? toDarkPalette(palette) : palette;
  }

  if (cuisine.includes('pizza')) {
    const palette = {
      accent: '#497DD5',
      surface: '#DCEBFF',
      badgeSurface: 'rgba(255, 255, 255, 0.28)',
      glow: 'rgba(171, 204, 255, 0.38)',
      shapePrimary: 'rgba(198, 221, 255, 0.46)',
      shapeSecondary: 'rgba(255, 255, 255, 0.62)',
      ctaSurface: '#FFFFFF',
      ctaText: '#3D6FC3',
      iconSurface: 'rgba(255, 255, 255, 0.3)',
      iconText: '#3D6FC3',
    };
    return mode === 'dark' ? toDarkPalette(palette) : palette;
  }

  if (cuisine.includes('thai')) {
    const palette = {
      accent: '#1C9E8B',
      surface: '#DFF9F2',
      badgeSurface: 'rgba(255, 255, 255, 0.28)',
      glow: 'rgba(170, 243, 226, 0.36)',
      shapePrimary: 'rgba(193, 248, 235, 0.48)',
      shapeSecondary: 'rgba(255, 255, 255, 0.62)',
      ctaSurface: '#FFFFFF',
      ctaText: '#198675',
      iconSurface: 'rgba(255, 255, 255, 0.3)',
      iconText: '#198675',
    };
    return mode === 'dark' ? toDarkPalette(palette) : palette;
  }

  if (
    offer.offer_type === 'COMBO_AFFINITY' ||
    offer.offer_type === 'FAVORITE_ITEM' ||
    offer.offer_type === 'ORDER_HISTORY_MATCH'
  ) {
    const palette = {
      accent: '#4877D0',
      surface: '#DDEAFF',
      badgeSurface: 'rgba(255, 255, 255, 0.28)',
      glow: 'rgba(174, 203, 255, 0.38)',
      shapePrimary: 'rgba(202, 221, 255, 0.46)',
      shapeSecondary: 'rgba(255, 255, 255, 0.62)',
      ctaSurface: '#FFFFFF',
      ctaText: '#3E69BA',
      iconSurface: 'rgba(255, 255, 255, 0.3)',
      iconText: '#3E69BA',
    };
    return mode === 'dark' ? toDarkPalette(palette) : palette;
  }

  if (
    offer.offer_type === 'FAVORITE_RESTAURANT' ||
    offer.offer_type === 'BUDGET_BEHAVIOR'
  ) {
    const palette = {
      accent: '#6C58C9',
      surface: '#ECE5FF',
      badgeSurface: 'rgba(255, 255, 255, 0.26)',
      glow: 'rgba(207, 193, 255, 0.36)',
      shapePrimary: 'rgba(226, 213, 255, 0.5)',
      shapeSecondary: 'rgba(255, 255, 255, 0.62)',
      ctaSurface: '#FFFFFF',
      ctaText: '#5D4AB7',
      iconSurface: 'rgba(255, 255, 255, 0.28)',
      iconText: '#5D4AB7',
    };
    return mode === 'dark' ? toDarkPalette(palette) : palette;
  }

  const palette = {
    accent: '#4A7FD8',
    surface: '#DDEBFF',
    badgeSurface: 'rgba(255, 255, 255, 0.28)',
    glow: 'rgba(174, 205, 255, 0.38)',
    shapePrimary: 'rgba(202, 222, 255, 0.46)',
    shapeSecondary: 'rgba(255, 255, 255, 0.62)',
    ctaSurface: '#FFFFFF',
    ctaText: '#3D70C5',
    iconSurface: 'rgba(255, 255, 255, 0.3)',
    iconText: '#3D70C5',
  };
  return mode === 'dark' ? toDarkPalette(palette) : palette;
}
