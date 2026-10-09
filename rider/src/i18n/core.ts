/**
 * The language rules, with no React in them, so a test (and the push handler,
 * which runs with no screen at all) can use them.
 *
 * Three languages: English, Hindi, Gujarati - the riders this fleet hires.
 * The rider's own choice wins; "system" follows the phone, and a phone in any
 * other language gets English rather than a guess.
 */

export type Language = 'en' | 'hi' | 'gu';
export type LanguagePreference = 'system' | Language;

export const LANGUAGES: readonly Language[] = ['en', 'hi', 'gu'];

/** "hi-IN", "gu_IN", "hi" -> the language; anything else -> English. */
export function detectLanguage(locale: string | null | undefined): Language {
  const code = (locale ?? '').toLowerCase().split(/[-_]/)[0];
  return code === 'hi' || code === 'gu' ? code : 'en';
}

export function resolveLanguage(
  preference: LanguagePreference,
  phoneLocale: string | null | undefined,
): Language {
  return preference === 'system' ? detectLanguage(phoneLocale) : preference;
}

/**
 * "{n} orders" + {n: 3} -> "3 orders". A name with no value stays as it is:
 * a visible "{name}" in a test screenshot beats a silent "undefined".
 */
export function fill(
  template: string,
  values: Record<string, string | number> = {},
): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in values ? String(values[name]) : whole,
  );
}

/** The phone's locale. Hermes' Intl reads it from Android; failing that, English. */
export function phoneLocale(): string | undefined {
  try {
    return Intl.DateTimeFormat().resolvedOptions().locale;
  } catch {
    return undefined;
  }
}
