import React from 'react';
import { StyleSheet, View } from 'react-native';

import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { AppText } from './AppText';
import { Icon, type IconName } from './Icon';

type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger';

export function Pill({ label, tone = 'neutral', icon, dot }: { label: string; tone?: Tone; icon?: IconName; dot?: boolean }) {
  const { colors } = useTheme();
  const palette = {
    neutral: { bg: colors.surfaceAlt, fg: colors.textMuted },
    primary: { bg: colors.primarySoft, fg: colors.primary },
    success: { bg: colors.successSoft, fg: colors.success },
    warning: { bg: colors.warningSoft, fg: colors.warning },
    danger: { bg: colors.dangerSoft, fg: colors.danger },
  }[tone];
  return (
    <View style={[styles.pill, { backgroundColor: palette.bg }]}>
      {dot ? <View style={[styles.dot, { backgroundColor: palette.fg }]} /> : null}
      {icon ? <Icon name={icon} size={14} color={palette.fg} /> : null}
      <AppText variant="micro" style={{ color: palette.fg }}>
        {label.toUpperCase()}
      </AppText>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xs,
    alignSelf: 'flex-start',
    paddingHorizontal: space.sm + 2,
    paddingVertical: space.xs,
    borderRadius: radius.pill,
  },
  dot: { width: 6, height: 6, borderRadius: 3 },
});
