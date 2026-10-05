import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { radius, space, type, useTheme } from '@/theme';
import { Icon, type IconName } from '@components/Icon';
import { PrimaryButton } from '@components/PrimaryButton';

interface StateViewProps {
  icon: IconName;
  title: string;
  body?: string;
  tone?: 'calm' | 'neutral' | 'danger';
  actionLabel?: string;
  onAction?: () => void;
  // Inline in a column or list rather than filling the screen.
  compact?: boolean;
  testID?: string;
}

// Every empty, error and fault state in the app. One component so a quiet
// service and a failed load never look alike: calm is green and reassuring,
// danger says what happened and what to do. The icon sits in a double ring —
// a soft halo around a tinted disc — which reads as deliberate rather than
// as a missing image.
export const StateView = ({
  icon,
  title,
  body,
  tone = 'neutral',
  actionLabel,
  onAction,
  compact = false,
  testID,
}: StateViewProps) => {
  const { colors } = useTheme();
  const iconColor =
    tone === 'calm' ? colors.accent : tone === 'danger' ? colors.danger : colors.textMuted;
  const tint =
    tone === 'calm' ? colors.accentSoft : tone === 'danger' ? colors.dangerSoft : colors.surfaceMuted;
  const disc = compact ? 52 : 76;
  return (
    <View testID={testID} style={[styles.container, compact ? styles.compact : styles.full]}>
      <View
        style={[
          styles.halo,
          { width: disc + 20, height: disc + 20, borderRadius: (disc + 20) / 2, borderColor: tint },
        ]}>
        <View
          style={[
            styles.disc,
            { width: disc, height: disc, borderRadius: disc / 2, backgroundColor: tint },
          ]}>
          <Icon name={icon} size={compact ? 24 : 34} color={iconColor} />
        </View>
      </View>
      <Text
        accessibilityRole="header"
        style={[compact ? styles.titleCompact : styles.title, { color: colors.text }]}>
        {title}
      </Text>
      {body ? (
        <Text style={[compact ? styles.bodyCompact : styles.body, { color: colors.textMuted }]}>
          {body}
        </Text>
      ) : null}
      {actionLabel && onAction ? (
        <View style={styles.action}>
          <PrimaryButton label={actionLabel} onPress={onAction} />
        </View>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { alignItems: 'center', justifyContent: 'center', gap: space.sm },
  full: { flex: 1, padding: space.xxxl },
  compact: { paddingVertical: space.xxl, paddingHorizontal: space.lg },
  halo: {
    borderWidth: 10,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.sm,
    opacity: 1,
  },
  disc: { alignItems: 'center', justifyContent: 'center' },
  title: { ...type.title, textAlign: 'center' },
  titleCompact: { ...type.heading, textAlign: 'center' },
  body: { ...type.body, textAlign: 'center', maxWidth: 440 },
  bodyCompact: { ...type.caption, textAlign: 'center', maxWidth: 280 },
  action: { marginTop: space.md, minWidth: 220, borderRadius: radius.md },
});
