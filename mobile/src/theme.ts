import React, {
  createContext,
  useContext,
  useMemo,
  type PropsWithChildren,
} from 'react';
import { useColorScheme } from 'react-native';
import { useSession, useThemePreference } from '@hooks/useAppStore';
import { DEFAULT_BRAND_COLOR, normalizeHex } from './themePalette';
import {
  createTheme,
  darkTheme,
  lightTheme,
  type AppTheme,
  type ThemeColors,
  type ThemeMode,
  type ThemePreference,
} from './themeBase';

// Re-exported so `@/theme` stays the one import site every screen already uses.
export { createTheme, darkTheme, lightTheme };
export type { AppTheme, ThemeColors, ThemeMode, ThemePreference };

const ThemeContext = createContext<AppTheme>(
  createTheme(DEFAULT_BRAND_COLOR, 'light'),
);

export function AppThemeProvider({
  children,
}: PropsWithChildren): React.JSX.Element {
  const themePreference = useThemePreference();
  const systemScheme = useColorScheme();
  const resolvedMode: ThemeMode =
    themePreference === 'system'
      ? systemScheme === 'dark'
        ? 'dark'
        : 'light'
      : themePreference;

  // The restaurant's colour, resolved from this build's own bundle ID at
  // startup and cached on the device. Absent on the very first launch and for
  // marketplace builds, where the default stands in.
  const { appConfig } = useSession();
  const brandColor = normalizeHex(appConfig?.branding?.primary_color);

  const value = useMemo(
    () => createTheme(brandColor, resolvedMode),
    [brandColor, resolvedMode],
  );

  return React.createElement(ThemeContext.Provider, { value }, children);
}

export function useTheme(): AppTheme {
  return useContext(ThemeContext);
}

export function useThemedStyles<T>(factory: (theme: AppTheme) => T): T {
  const activeTheme = useTheme();
  return useMemo(() => factory(activeTheme), [activeTheme, factory]);
}
