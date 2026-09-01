import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react';
import { normalizeHex } from './palette';
import { createTheme, type AppTheme, type ThemeMode, type ThemePreference } from './themeBase';
import { ThemeContext } from './ThemeContext';
import { applyTheme } from './applyTheme';

export type { AppTheme, ThemeMode, ThemePreference };

const PREFERENCE_KEY = 'restaurant-rag-customer-theme-preference';

/**
 * What a visitor who has never chosen gets.
 *
 * Light, not `system`. The storefront is the restaurant's shop window: the
 * food photography, the warm brand washes and the menu tiles are all designed
 * against a light ground, and most visitors arrive without ever opening the
 * appearance switcher. Defaulting to `system` handed anyone whose laptop is in
 * dark mode a dark storefront they never asked for.
 *
 * Dark mode is unchanged and one tap away in Profile > Appearance, including
 * the `system` option for anyone who does want to follow their device.
 */
const DEFAULT_PREFERENCE: ThemePreference = 'light';

function readPreference(): ThemePreference {
  try {
    const raw = window.localStorage.getItem(PREFERENCE_KEY);
    return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : DEFAULT_PREFERENCE;
  } catch {
    return DEFAULT_PREFERENCE;
  }
}

/**
 * Resolves the palette and publishes it to CSS.
 *
 * Two inputs, exactly as on the phone: the restaurant's colour, which arrives
 * from `/app-config`, and the viewer's light/dark/system preference. Neither is
 * available on the very first paint, so the default brand in light mode is what
 * `index.html` ships as inline tokens and this only ever refines it.
 */
export function ThemeProvider({
  brandColor,
  children,
}: PropsWithChildren<{ brandColor: string | null | undefined }>) {
  const [preference, setPreferenceState] = useState<ThemePreference>(readPreference);
  const [systemMode, setSystemMode] = useState<ThemeMode>(() =>
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light',
  );

  useEffect(() => {
    if (typeof window.matchMedia !== 'function') {
      return;
    }
    const query = window.matchMedia('(prefers-color-scheme: dark)');
    const handle = (event: MediaQueryListEvent) =>
      setSystemMode(event.matches ? 'dark' : 'light');
    query.addEventListener('change', handle);
    return () => query.removeEventListener('change', handle);
  }, []);

  const setPreference = useCallback((value: ThemePreference) => {
    setPreferenceState(value);
    try {
      window.localStorage.setItem(PREFERENCE_KEY, value);
    } catch {
      // A blocked storage quota must not stop the theme from changing.
    }
  }, []);

  const mode: ThemeMode = preference === 'system' ? systemMode : preference;
  const theme = useMemo(
    () => createTheme(normalizeHex(brandColor), mode),
    [brandColor, mode],
  );

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const value = useMemo(
    () => ({ theme, preference, systemMode, setPreference }),
    [preference, setPreference, systemMode, theme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

