import React, { createContext, useContext, useMemo } from 'react';
import { useColorScheme } from 'react-native';

import { dark, light, type Palette, type ThemeMode } from './tokens';

type Theme = { mode: ThemeMode; colors: Palette };

const ThemeContext = createContext<Theme>({ mode: 'dark', colors: dark });

/**
 * Dark unless the phone says light. A preference toggle can be added on top
 * later (Profile); the default must be right without anyone touching it.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const scheme = useColorScheme();
  const value = useMemo<Theme>(
    () => (scheme === 'light' ? { mode: 'light', colors: light } : { mode: 'dark', colors: dark }),
    [scheme],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme {
  return useContext(ThemeContext);
}
