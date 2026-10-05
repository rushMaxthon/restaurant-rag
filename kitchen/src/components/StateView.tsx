import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
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
// danger says what happened and what to do.
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
  const iconBackground =
    tone === 'calm' ? colors.accentSoft : tone === 'danger' ? colors.dangerSoft : colors.surfaceMuted;
  return (
    <View testID={testID} style={[styles.container, compact ? styles.compact : styles.full]}>
      <View
        style={[
          styles.iconWrap,
          compact && styles.iconWrapCompact,
          { backgroundColor: iconBackground },
        ]}>
        <Icon name={icon} size={compact ? 22 : 30} color={iconColor} />
      </View>
      <Text
        accessibilityRole="header"
        style={[styles.title, compact && styles.titleCompact, { color: colors.text }]}>
        {title}
      </Text>
      {body ? (
        <Text style={[styles.body, compact && styles.bodyCompact, { color: colors.textMuted }]}>
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
  container: { alignItems: 'center', justifyContent: 'center', gap: 10 },
  full: { flex: 1, padding: 32 },
  compact: { paddingVertical: 28, paddingHorizontal: 16 },
  iconWrap: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 4,
  },
  iconWrapCompact: { width: 48, height: 48, borderRadius: 24 },
  title: { fontSize: 22, fontWeight: '800', textAlign: 'center' },
  titleCompact: { fontSize: 17 },
  body: { fontSize: 16, lineHeight: 23, textAlign: 'center', maxWidth: 420 },
  bodyCompact: { fontSize: 14, lineHeight: 20 },
  action: { marginTop: 12, minWidth: 220 },
});
