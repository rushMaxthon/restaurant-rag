import React from 'react';
import { ActivityIndicator, Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';

/**
 * A settings section: one card, rows split by hairlines. A card per row made
 * Profile three screens long for eight switches; grouped, it is one.
 */
export function Group({
  title,
  children,
}: {
  title?: string;
  children: React.ReactNode;
}) {
  const { colors } = useTheme();
  const rows = React.Children.toArray(children).filter(Boolean);
  return (
    <View style={styles.group}>
      {title ? (
        <AppText variant="micro" tone="muted" style={styles.title}>
          {title}
        </AppText>
      ) : null}
      <Card padded={false} style={styles.card}>
        {rows.map((row, i) => (
          <View
            key={i}
            style={
              i > 0
                ? [styles.divided, { borderTopColor: colors.border }]
                : undefined
            }
          >
            {row}
          </View>
        ))}
      </Card>
    </View>
  );
}

/** One row of a Group. `tone="danger"` is for leaving, never for a setting. */
export function GroupRow({
  icon,
  label,
  value,
  onPress,
  trailing,
  tone,
  busy = false,
}: {
  icon: IconName;
  label: string;
  value?: string;
  onPress?: () => void;
  trailing?: React.ReactNode;
  tone?: 'danger';
  busy?: boolean;
}) {
  const { colors } = useTheme();
  const ink = tone === 'danger' ? colors.danger : colors.text;
  return (
    <Pressable
      onPress={busy ? undefined : onPress}
      disabled={!onPress}
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={value ? `${label}, ${value}` : label}
      android_ripple={{ color: colors.border }}
      style={styles.row}
    >
      <Icon name={icon} size={20} color={ink} />
      <AppText
        variant="bodyStrong"
        tone={tone === 'danger' ? 'danger' : 'default'}
        style={styles.flex}
        numberOfLines={1}
      >
        {label}
      </AppText>
      {value ? (
        <AppText variant="label" tone="muted" numberOfLines={1}>
          {value}
        </AppText>
      ) : null}
      {busy ? <ActivityIndicator size="small" color={ink} /> : trailing}
      {onPress && !trailing && !busy && tone !== 'danger' ? (
        <Icon name="chevron-forward" size={16} color={colors.textFaint} />
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  group: { gap: space.sm },
  // Clips the row ripple to the rounded corners.
  card: { overflow: 'hidden' },
  title: { marginLeft: space.xs },
  flex: { flex: 1 },
  divided: { borderTopWidth: StyleSheet.hairlineWidth },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    minHeight: 56,
    paddingHorizontal: space.lg,
    paddingVertical: space.sm,
  },
});
