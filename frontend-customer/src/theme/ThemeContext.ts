import { createContext } from 'react';
import { DEFAULT_BRAND_COLOR } from './palette';
import { createTheme, type AppTheme, type ThemeMode, type ThemePreference } from './themeBase';

export interface ThemeContextValue {
  theme: AppTheme;
  preference: ThemePreference;
  /** What `system` currently resolves to, so a screen can label the choice. */
  systemMode: ThemeMode;
  setPreference: (value: ThemePreference) => void;
}

export const ThemeContext = createContext<ThemeContextValue>({
  theme: createTheme(DEFAULT_BRAND_COLOR, 'light'),
  preference: 'system',
  systemMode: 'light',
  setPreference: () => undefined,
});

