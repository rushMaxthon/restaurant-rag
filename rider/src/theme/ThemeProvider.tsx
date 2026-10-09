import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { useColorScheme } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { highContrast as strengthen } from './contrast';
import {
  decodePreference,
  resolveMode,
  THEME_KEY,
  type ThemePreference,
} from './preference';
import { dark, light, type Palette, type ThemeMode } from './tokens';

type Theme = {
  mode: ThemeMode;
  colors: Palette;
  /** System, light or dark - the rider's choice on Profile. */
  preference: ThemePreference;
  setPreference: (next: ThemePreference) => void;
  highContrast: boolean;
  setHighContrast: (on: boolean) => void;
};

const ThemeContext = createContext<Theme>({
  mode: 'dark',
  colors: dark,
  preference: 'system',
  setPreference: () => {},
  highContrast: false,
  setHighContrast: () => {},
});

const CONTRAST_KEY = 'rider.highContrast';

/**
 * Dark unless the phone says light, unless the rider chose otherwise. High
 * contrast is the one preference on top, for reading the screen in the sun.
 * Both are kept on this phone; a storage failure just means the default.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const scheme = useColorScheme();
  const [contrast, setContrast] = useState(false);
  const [preference, setPref] = useState<ThemePreference>('system');

  useEffect(() => {
    AsyncStorage.getItem(CONTRAST_KEY)
      .then(v => setContrast(v === '1'))
      .catch(() => {});
    AsyncStorage.getItem(THEME_KEY)
      .then(v => setPref(decodePreference(v)))
      .catch(() => {});
  }, []);

  const setHighContrast = useCallback((on: boolean) => {
    setContrast(on);
    AsyncStorage.setItem(CONTRAST_KEY, on ? '1' : '0').catch(() => {});
  }, []);

  const setPreference = useCallback((next: ThemePreference) => {
    setPref(next);
    AsyncStorage.setItem(THEME_KEY, next).catch(() => {});
  }, []);

  const value = useMemo<Theme>(() => {
    const mode = resolveMode(preference, scheme);
    const base = mode === 'light' ? light : dark;
    return {
      mode,
      colors: contrast ? strengthen(base) : base,
      preference,
      setPreference,
      highContrast: contrast,
      setHighContrast,
    };
  }, [scheme, contrast, preference, setPreference, setHighContrast]);
  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme(): Theme {
  return useContext(ThemeContext);
}
