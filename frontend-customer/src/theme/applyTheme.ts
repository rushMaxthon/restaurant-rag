/**
 * Publishing a resolved theme to CSS.
 *
 * The app builds its palette in TypeScript and hands each screen a `theme`
 * object. The web cannot do that without threading a context through every
 * rule in a stylesheet, so the same palette is written to CSS custom
 * properties on the root element instead: `theme.colors.primary` becomes
 * `--primary`, and every rule in `app.css` reads the token.
 *
 * The consequence is the one the app has and the web did not: changing the
 * restaurant's colour, or flipping to dark mode, restyles the entire UI in one
 * assignment with no component re-render and no stylesheet swap.
 *
 * Only the keys below are published. They are named for the app's own tokens
 * so a value can be traced from `themeBase.ts` to a CSS rule by name alone.
 */

import type { AppTheme } from './themeBase';
import { hexToRgb, tint } from './palette';

/** Tokens the app expresses as shadow objects, which CSS states as one string. */
function shadows(theme: AppTheme): Record<string, string> {
  const s = theme.colors.shadow;
  return {
    '--shadow-xs': `0 2px 6px ${s}`,
    '--shadow-sm': `0 4px 10px ${s}`,
    '--shadow-md': `0 6px 14px ${s}`,
    '--shadow-lg': `0 10px 24px ${s}`,
    '--shadow-xl': `0 16px 38px ${s}`,
  };
}

export function themeVariables(theme: AppTheme): Record<string, string> {
  const c = theme.colors;
  const { r, g, b } = hexToRgb(c.primary);

  return {
    // --- brand ---------------------------------------------------------
    '--primary': c.primary,
    '--primary-rgb': `${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}`,
    '--primary-soft': c.primarySoft,
    '--on-primary': c.onPrimary,
    '--brand': theme.brandColor,

    // --- surfaces ------------------------------------------------------
    '--bg': c.background,
    '--card': c.card,
    '--surface': c.surface,
    '--surface-alt': c.surfaceAlt,
    '--surface-raised': c.surfaceRaised,
    '--modal-surface': c.modalSurface,
    '--input': c.input,
    '--cream': c.cream,
    '--chip': c.chip,
    '--chip-border': c.chipBorder,

    // --- ink -----------------------------------------------------------
    '--text': c.text,
    '--muted': c.secondaryText,
    '--hint': c.hint,
    '--disabled-text': c.disabledText,

    // --- semantic ------------------------------------------------------
    '--success': c.success,
    '--success-soft': c.successSoft,
    '--warning': c.warning,
    '--warning-soft': c.warningSoft,
    '--info': c.info,
    '--info-soft': c.infoSoft,
    '--danger': c.deepRed,
    // The same colour under the name five legacy rules ask for.
    '--deep-red': c.deepRed,
    '--danger-soft': c.dangerSoft,
    '--offer': c.offer,
    '--white': c.white,
    // Deliberately not theme-dependent: this is ink over a photo, and the
    // scrim under it is dark in both themes.
    '--on-media': c.white,

    // --- lines and veils -----------------------------------------------
    '--border': c.border,
    '--divider': c.divider,
    '--overlay': c.overlay,
    '--skeleton-base': c.skeletonBase,
    '--skeleton-highlight': c.skeletonHighlight,
    '--shadow-color': c.shadow,

    // --- brand washes ---------------------------------------------------
    // The literals the phone's stylesheets carry, passed through `tone` so a
    // rebranded app gets a wash of its own colour rather than a peach one.
    '--wash-hero': theme.mode === 'dark' ? c.surfaceAlt : theme.tone('#FFF2EA'),
    '--wash-ai': theme.mode === 'dark' ? c.surfaceAlt : theme.tone('#FFF5EE'),
    '--wash-chip-active': theme.mode === 'dark' ? c.primarySoft : theme.tone('#FFF2EB'),
    '--brand-line': theme.mode === 'dark' ? c.border : theme.tone('#FFD8C7'),
    '--brand-line-soft': theme.mode === 'dark' ? c.border : theme.tone('#FFE0D1'),
    '--glow-primary': theme.primaryTint(0.12),
    '--glow-secondary': theme.tone('rgba(255, 189, 153, 0.35)'),
    '--tint-08': tint(c.primary, 0.08),
    '--tint-12': tint(c.primary, 0.12),
    '--tint-16': tint(c.primary, 0.16),
    '--tint-24': tint(c.primary, 0.24),

    ...shadows(theme),
  };
}

/**
 * Write the theme onto the document.
 *
 * `color-scheme` is set alongside the tokens so the browser's own chrome —
 * scrollbars, form controls, the address bar on mobile — follows the app
 * instead of staying light under a dark palette.
 */
export function applyTheme(theme: AppTheme): void {
  const root = document.documentElement;
  const vars = themeVariables(theme);
  for (const [name, value] of Object.entries(vars)) {
    root.style.setProperty(name, value);
  }
  root.style.colorScheme = theme.mode;
  root.dataset.theme = theme.mode;

  // The installed-app title bar and the iOS status bar read this, so a dark
  // palette does not leave a white band above the app.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta instanceof HTMLMetaElement) {
    meta.content = theme.colors.background;
  }
}
