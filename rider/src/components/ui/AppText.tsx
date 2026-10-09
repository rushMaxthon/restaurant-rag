import React from 'react';
import { Text, type TextProps } from 'react-native';

import { useTheme } from '@theme/ThemeProvider';
import { type as typeScale } from '@theme/tokens';

type Variant = keyof typeof typeScale;
type Tone = 'default' | 'muted' | 'faint' | 'primary' | 'success' | 'warning' | 'danger' | 'onPrimary';

export type AppTextProps = TextProps & { variant?: Variant; tone?: Tone; align?: 'left' | 'center' | 'right' };

/**
 * The only Text the app uses, so every string is set in the bundled face at a
 * size from the scale. `allowFontScaling` stays on (riders with large system
 * text must still read it), capped so a layout does not burst.
 */
export function AppText({ variant = 'body', tone = 'default', align, style, ...rest }: AppTextProps) {
  const { colors } = useTheme();
  const color = {
    default: colors.text,
    muted: colors.textMuted,
    faint: colors.textFaint,
    primary: colors.primary,
    success: colors.success,
    warning: colors.warning,
    danger: colors.danger,
    onPrimary: colors.onPrimary,
  }[tone];
  return (
    <Text
      maxFontSizeMultiplier={1.4}
      {...rest}
      style={[typeScale[variant], { color, textAlign: align }, style]}
    />
  );
}
