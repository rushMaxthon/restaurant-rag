import {
  COUNTRIES,
  DEFAULT_COUNTRY,
  type CountryOption,
} from '@/data/countries';

export function getCountryFlagEmoji(countryCode: string): string {
  return countryCode
    .toUpperCase()
    .split('')
    .map(character => String.fromCodePoint(127397 + character.charCodeAt(0)))
    .join('');
}

export function sanitizeLocalPhoneNumber(value: string): string {
  return value.replace(/\D/g, '');
}

export function normalizeStoredPhoneNumber(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return '';
  }
  if (trimmed.startsWith('+')) {
    return `+${trimmed.slice(1).replace(/\D/g, '')}`;
  }
  return trimmed.replace(/\D/g, '');
}

export function buildInternationalPhoneNumber(
  country: CountryOption,
  localPhoneNumber: string,
): string {
  return `${country.dialCode}${sanitizeLocalPhoneNumber(localPhoneNumber)}`;
}

export function isValidPhoneNumberForCountry(
  localPhoneNumber: string,
  country: CountryOption,
): boolean {
  const sanitized = sanitizeLocalPhoneNumber(localPhoneNumber);
  return (
    sanitized.length >= country.minLength &&
    sanitized.length <= country.maxLength
  );
}

export function getCountryByCode(code?: string | null): CountryOption {
  if (!code) {
    return DEFAULT_COUNTRY;
  }
  return COUNTRIES.find(country => country.code === code) ?? DEFAULT_COUNTRY;
}

export function getCountryByDialCode(dialCode?: string | null): CountryOption {
  if (!dialCode) {
    return DEFAULT_COUNTRY;
  }
  return (
    COUNTRIES.find(country => country.dialCode === dialCode) ?? DEFAULT_COUNTRY
  );
}
