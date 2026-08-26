import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface HomeSectionHeaderProps {
  title: string;
  subtitle?: string;
  actionLabel?: string;
  onActionPress?: () => void;
}

function HomeSectionHeaderComponent({
  title,
  subtitle,
  actionLabel,
  onActionPress,
}: HomeSectionHeaderProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.row}>
      <View style={styles.copy}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
      </View>
      {actionLabel && onActionPress ? (
        <Pressable onPress={onActionPress} style={styles.action}>
          <Text style={styles.actionLabel}>{actionLabel}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    row: {
      flexDirection: 'row',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: theme.spacing.md,
    },
    copy: {
      flex: 1,
      gap: 4,
    },
    title: {
      color: theme.colors.text,
      fontSize: 20,
      fontWeight: '800',
    },
    subtitle: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 18,
    },
    action: {
      paddingVertical: 6,
    },
    actionLabel: {
      color: theme.colors.primary,
      fontWeight: '700',
    },
  });


/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const HomeSectionHeader = React.memo(HomeSectionHeaderComponent);
