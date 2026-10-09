import {
  fill,
  phoneLocale,
  resolveLanguage,
  type Language,
} from './core';
import { en, gu, hi, type Key } from './strings';

/**
 * Translation with no React and no storage in it, so pure helpers and their
 * tests can use it (AsyncStorage does not load under jest).
 *
 * The language in force lives here at module level as well as in React: the
 * push handler and the shift service's notification run with no screen
 * mounted, and helpers like `greeting` are called from render without a
 * hook. `LanguageProvider` sets it BEFORE rendering its children, so a
 * re-render after a switch reads the new language everywhere.
 */
let current: Language = resolveLanguage('system', phoneLocale());

export const DICTIONARIES: Record<Language, Record<Key, string>> = { en, hi, gu };

export type Values = Record<string, string | number>;

export function setCurrentLanguage(lang: Language): void {
  current = lang;
}

export function currentLanguage(): Language {
  return current;
}

/** A sentence in the current language; English when a key is somehow missing. */
export function translate(key: Key, values?: Values): string {
  return fill(DICTIONARIES[current][key] ?? en[key] ?? key, values);
}

/** `count` picks `.one` or `.other`; the count is also passed in as `{n}`. */
export function plural(
  base: string,
  count: number,
  values: Values = {},
): string {
  const key = `${base}.${count === 1 ? 'one' : 'other'}` as Key;
  return translate(key, { n: count, ...values });
}
