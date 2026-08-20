export type CountryOption = {
  code: string;
  name: string;
  dialCode: string;
  minLength: number;
  maxLength: number;
};

export const COUNTRIES: CountryOption[] = [
  { code: 'IN', name: 'India', dialCode: '+91', minLength: 10, maxLength: 10 },
  { code: 'US', name: 'United States', dialCode: '+1', minLength: 10, maxLength: 10 },
  { code: 'GB', name: 'United Kingdom', dialCode: '+44', minLength: 10, maxLength: 11 },
  { code: 'AE', name: 'United Arab Emirates', dialCode: '+971', minLength: 9, maxLength: 9 },
  { code: 'AU', name: 'Australia', dialCode: '+61', minLength: 9, maxLength: 9 },
  { code: 'BD', name: 'Bangladesh', dialCode: '+880', minLength: 10, maxLength: 10 },
  { code: 'CA', name: 'Canada', dialCode: '+1', minLength: 10, maxLength: 10 },
  { code: 'DE', name: 'Germany', dialCode: '+49', minLength: 10, maxLength: 11 },
  { code: 'EG', name: 'Egypt', dialCode: '+20', minLength: 10, maxLength: 10 },
  { code: 'ES', name: 'Spain', dialCode: '+34', minLength: 9, maxLength: 9 },
  { code: 'FR', name: 'France', dialCode: '+33', minLength: 9, maxLength: 9 },
  { code: 'HK', name: 'Hong Kong', dialCode: '+852', minLength: 8, maxLength: 8 },
  { code: 'ID', name: 'Indonesia', dialCode: '+62', minLength: 9, maxLength: 12 },
  { code: 'IE', name: 'Ireland', dialCode: '+353', minLength: 9, maxLength: 9 },
  { code: 'IT', name: 'Italy', dialCode: '+39', minLength: 9, maxLength: 10 },
  { code: 'JP', name: 'Japan', dialCode: '+81', minLength: 10, maxLength: 10 },
  { code: 'KE', name: 'Kenya', dialCode: '+254', minLength: 9, maxLength: 9 },
  { code: 'KW', name: 'Kuwait', dialCode: '+965', minLength: 8, maxLength: 8 },
  { code: 'LK', name: 'Sri Lanka', dialCode: '+94', minLength: 9, maxLength: 9 },
  { code: 'MY', name: 'Malaysia', dialCode: '+60', minLength: 9, maxLength: 10 },
  { code: 'NP', name: 'Nepal', dialCode: '+977', minLength: 10, maxLength: 10 },
  { code: 'NZ', name: 'New Zealand', dialCode: '+64', minLength: 8, maxLength: 10 },
  { code: 'OM', name: 'Oman', dialCode: '+968', minLength: 8, maxLength: 8 },
  { code: 'PH', name: 'Philippines', dialCode: '+63', minLength: 10, maxLength: 10 },
  { code: 'PK', name: 'Pakistan', dialCode: '+92', minLength: 10, maxLength: 10 },
  { code: 'QA', name: 'Qatar', dialCode: '+974', minLength: 8, maxLength: 8 },
  { code: 'SA', name: 'Saudi Arabia', dialCode: '+966', minLength: 9, maxLength: 9 },
  { code: 'SG', name: 'Singapore', dialCode: '+65', minLength: 8, maxLength: 8 },
  { code: 'TH', name: 'Thailand', dialCode: '+66', minLength: 9, maxLength: 9 },
  { code: 'TR', name: 'Turkey', dialCode: '+90', minLength: 10, maxLength: 10 },
  { code: 'ZA', name: 'South Africa', dialCode: '+27', minLength: 9, maxLength: 9 },
];

export const DEFAULT_COUNTRY = COUNTRIES[0];
