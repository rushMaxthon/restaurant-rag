import React, {
  createContext,
  useContext,
  useMemo,
  type PropsWithChildren,
} from 'react';
import { useColorScheme } from 'react-native';
import { useThemePreference } from '@hooks/useAppStore';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ThemeMode = 'light' | 'dark';

const spacing = {
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  screen: 16,
  stackTop: 10,
  card: 16,
  gap: 12,
  section: 24,
} as const;

const radius = {
  xs: 10,
  md: 16,
  lg: 20,
  card: 12,
  button: 8,
  pill: 20,
} as const;

const sharedColors = {
  primary: '#FF5200',
  deepRed: '#CB202D',
  success: '#48C479',
  warning: '#F8A000',
  info: '#1A73E8',
  offer: '#3D9B6D',
  white: '#FFFFFF',
} as const;

export const lightTheme = {
  mode: 'light' as const,
  colors: {
    ...sharedColors,
    background: '#FFFFFF',
    card: '#F8F8F8',
    surface: '#FFFDF9',
    surfaceAlt: '#FFF5EE',
    surfaceRaised: '#FFFFFF',
    modalSurface: '#FFFDF9',
    input: '#FFFFFF',
    text: '#282C3F',
    secondaryText: '#686B78',
    hint: '#93959F',
    disabledText: '#A8ABB5',
    onPrimary: '#FFFFFF',
    successSoft: '#E8F7EE',
    warningSoft: '#FFF4DA',
    infoSoft: '#E9F1FF',
    dangerSoft: '#FFF2F1',
    border: '#E9E9EB',
    divider: '#F2F2F2',
    sidebar: '#1A1A2E',
    primarySoft: '#FFF0E8',
    cream: '#FFF8F2',
    chip: '#FAF7F3',
    chipBorder: '#F0E7DF',
    overlay: 'rgba(16, 18, 28, 0.26)',
    skeletonBase: '#F0F0F0',
    skeletonHighlight: '#E0E0E0',
    shadow: 'rgba(20, 23, 34, 0.12)',
    darkOverlay: 'rgba(16, 18, 28, 0.26)',
  },
  spacing,
  radius,
};

export const darkTheme = {
  mode: 'dark' as const,
  colors: {
    ...sharedColors,
    primary: '#FF7A45',
    background: '#0E1116',
    card: '#151A22',
    surface: '#12171F',
    surfaceAlt: '#1A202B',
    surfaceRaised: '#1C2430',
    modalSurface: '#151C26',
    input: '#1A202B',
    text: '#F3F5F8',
    secondaryText: '#B5BDC9',
    hint: '#8791A1',
    disabledText: '#6F7A8B',
    onPrimary: '#FFF8F4',
    successSoft: 'rgba(72, 196, 121, 0.14)',
    warningSoft: 'rgba(248, 160, 0, 0.14)',
    infoSoft: 'rgba(26, 115, 232, 0.16)',
    dangerSoft: 'rgba(203, 32, 45, 0.16)',
    border: '#252C38',
    divider: '#1D2430',
    sidebar: '#0B0E13',
    primarySoft: 'rgba(255, 122, 69, 0.12)',
    cream: '#181D26',
    chip: '#1A202B',
    chipBorder: '#2A3340',
    overlay: 'rgba(8, 10, 14, 0.52)',
    skeletonBase: '#1A202B',
    skeletonHighlight: '#232C38',
    shadow: 'rgba(0, 0, 0, 0.34)',
    darkOverlay: 'rgba(8, 10, 14, 0.42)',
  },
  spacing,
  radius,
};

export type AppTheme = typeof lightTheme | typeof darkTheme;

const ThemeContext = createContext<AppTheme>(lightTheme);

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

  const value = useMemo(
    () => (resolvedMode === 'dark' ? darkTheme : lightTheme),
    [resolvedMode],
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

export const theme = lightTheme;
