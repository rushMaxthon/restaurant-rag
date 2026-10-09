import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

import {
  fill,
  phoneLocale,
  resolveLanguage,
  type Language,
  type LanguagePreference,
} from './core';
import { en, type Key } from './strings';
import {
  DICTIONARIES,
  plural,
  setCurrentLanguage,
  type Values,
} from './translate';

export type { Key } from './strings';
export type { Language, LanguagePreference } from './core';
export {
  currentLanguage,
  plural,
  translate,
  type Values,
} from './translate';

export const LANGUAGE_KEY = 'rider.lang';

function decodePreference(raw: string | null): LanguagePreference {
  return raw === 'en' || raw === 'hi' || raw === 'gu' ? raw : 'system';
}

/** For headless work (a push that starts a killed app): read the choice first. */
export async function initLanguage(): Promise<Language> {
  let pref: LanguagePreference = 'system';
  try {
    pref = decodePreference(await AsyncStorage.getItem(LANGUAGE_KEY));
  } catch {
    // unreadable storage: the phone's language stands
  }
  const lang = resolveLanguage(pref, phoneLocale());
  setCurrentLanguage(lang);
  return lang;
}

/** Each language named in itself, so a rider who cannot read the others finds theirs. */
export const LANGUAGE_NAMES: Record<Language, string> = {
  en: 'English',
  hi: 'हिन्दी',
  gu: 'ગુજરાતી',
};

type I18n = {
  lang: Language;
  preference: LanguagePreference;
  setPreference: (next: LanguagePreference) => void;
  /** Bound to the language in force; changes identity when it changes. */
  t: (key: Key, values?: Values) => string;
  plural: typeof plural;
};

const I18nContext = createContext<I18n | null>(null);

export function LanguageProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPref] = useState<LanguagePreference>('system');
  const lang = resolveLanguage(preference, phoneLocale());
  // Set during render, before the children read it (see translate.ts).
  setCurrentLanguage(lang);

  useEffect(() => {
    let alive = true;
    AsyncStorage.getItem(LANGUAGE_KEY)
      .then(raw => {
        if (alive) setPref(decodePreference(raw));
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const setPreference = useCallback((next: LanguagePreference) => {
    setPref(next);
    AsyncStorage.setItem(LANGUAGE_KEY, next).catch(() => {});
  }, []);

  const value = useMemo<I18n>(
    () => ({
      lang,
      preference,
      setPreference,
      // A new function per language, so memoised children re-render on a switch.
      t: (key, values) => fill(DICTIONARIES[lang][key] ?? en[key], values),
      plural,
    }),
    [lang, preference, setPreference],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error('useI18n outside LanguageProvider');
  return value;
}
