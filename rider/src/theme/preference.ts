import type { Key } from '@/i18n/strings';
import type { ThemeMode } from './tokens';

/** System follows the phone; the other two are the rider's own choice. */
export type ThemePreference = 'system' | ThemeMode;

export const THEME_KEY = 'rider.theme';

/** Keys, not words: resolved with t() where drawn, so a language switch reaches them. */
export const THEME_OPTIONS: readonly {
  key: ThemePreference;
  labelKey: Key;
  hintKey: Key;
}[] = [
  {
    key: 'system',
    labelKey: 'account.theme.systemLabel',
    hintKey: 'account.theme.systemHint',
  },
  {
    key: 'light',
    labelKey: 'account.profile.light',
    hintKey: 'account.theme.lightHint',
  },
  {
    key: 'dark',
    labelKey: 'account.profile.dark',
    hintKey: 'account.theme.darkHint',
  },
];

export function resolveMode(
  preference: ThemePreference,
  scheme: 'light' | 'dark' | null | undefined,
): ThemeMode {
  if (preference !== 'system') return preference;
  return scheme === 'light' ? 'light' : 'dark';
}

export function decodePreference(raw: string | null): ThemePreference {
  return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system';
}
