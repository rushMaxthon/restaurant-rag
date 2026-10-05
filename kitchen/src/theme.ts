import React, { createContext, useContext, useMemo } from 'react';
import { useColorScheme } from 'react-native';
import { createTheme, darkTheme, lightTheme } from './themeBase';
import type { AppTheme, ThemeColors, ThemeMode, ThemePreference } from './themeBase';

export { createTheme, darkTheme, lightTheme };
export type { AppTheme, ThemeColors, ThemeMode, ThemePreference };

const ThemeContext = createContext<AppTheme>(createTheme('light'));

export const AppThemeProvider = ({ children }: { children: React.ReactNode }) => {
  const scheme = useColorScheme();
  const theme = useMemo(
    () => createTheme(scheme === 'dark' ? 'dark' : 'light'),
    [scheme],
  );
  return React.createElement(ThemeContext.Provider, { value: theme }, children);
};

export function useTheme(): AppTheme {
  return useContext(ThemeContext);
}

export function useThemedStyles<T>(factory: (theme: AppTheme) => T): T {
  const theme = useTheme();
  return useMemo(() => factory(theme), [factory, theme]);
}
