import type { Palette } from '@theme/tokens';

/**
 * The colours the illustration templates name (`scenes.ts`), from the
 * theme. Most follow it; a few are drawn things that keep their colour in
 * the dark (skin, trousers, a paper bag, the sun).
 */
export function illustrationPalette(
  colors: Palette,
  mode: 'light' | 'dark',
): Record<string, string> {
  const dark = mode === 'dark';
  return {
    P: colors.primary,
    PD: '#D94600',
    PS: colors.primarySoft,
    G: dark ? '#232836' : '#E6E9F0',
    L: dark ? '#9AA3B8' : '#2A3042',
    B: dark ? '#2A3040' : '#FFFFFF',
    BE: dark ? '#3A4256' : '#DCE1EA',
    SC: dark ? '#E9ECF2' : '#FFFFFF',
    SK: '#F1B88F',
    HR: '#2A2F3B',
    JN: '#33415E',
    S: colors.success,
    SS: colors.successSoft,
    W: '#F5A524',
    K: '#D9A66B',
    M: colors.textMuted,
    WH: '#FFFFFF',
  };
}

/** `{P}` -> the colour; an unknown token is left as is, so a typo shows. */
export function fillTemplate(
  template: string,
  palette: Record<string, string>,
): string {
  return template.replace(
    /\{([A-Z]{1,2})\}/g,
    (whole, key: string) => palette[key] ?? whole,
  );
}
