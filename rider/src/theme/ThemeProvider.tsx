import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { useColorScheme } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { highContrast as strengthen } from './contrast';
import { dark, light, type Palette, type ThemeMode } from './tokens';

type Theme = {
  mode: ThemeMode;
  colors: Palette;
  highContrast: boolean;
  setHighContrast: (on: boolean) => void;
};

const ThemeContext = createContext<Theme>({
  mode: 'dark',
  colors: dark,
  highContrast: false,
  setHighContrast: () => {},
});

const CONTRAST_KEY = 'rider.highContrast';

/**
 * Dark unless the phone says light. High contrast is the one preference on
 * top, for reading the screen in the sun; it is kept on this phone, and a
 * storage failure just means the default.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const scheme = useColorScheme();
  const [contrast, setContrast] = useState(false);

  useEffect(() => {
    AsyncStorage.getItem(CONTRAST_KEY)
      .then(v => setContrast(v === '1'))
      .catch(() => {});
  }, []);

  const setHighContrast = useCallback((on: boolean) => {
    setContrast(on);
    AsyncStorage.setItem(CONTRAST_KEY, on ? '1' : '0').catch(() => {});
  }, []);

  const value = useMemo<Theme>(() => {
    const mode: ThemeMode = scheme === 'light' ? 'light' : 'dark';
    const base = mode === 'light' ? light : dark;
    return { mode, colors: contrast ? strengthen(base) : base, highContrast: contrast, setHighContrast };
  }, [scheme, contrast, setHighContrast]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  return useContext(ThemeContext);
}
