import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

export interface ProfileRowProps {
  title: string;
  subtitle: string;
  icon: string;
  onPress: () => void;
}

function ProfileRowComponent({
  title,
  subtitle,
  icon,
  onPress,
}: ProfileRowProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <Pressable onPress={onPress} style={styles.sectionRow}>
      <View style={styles.sectionIcon}>
        <Icon color={theme.colors.primary} name={icon} size={18} />
      </View>
      <View style={styles.sectionCopy}>
        <Text style={styles.sectionTitle}>{title}</Text>
        <Text style={styles.sectionSubtitle}>{subtitle}</Text>
      </View>
      <Icon color={theme.colors.hint} name="chevron-forward" size={18} />
    </Pressable>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    sectionRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      paddingVertical: 14,
      borderBottomWidth: 1,
      borderBottomColor: theme.colors.divider,
    },
    sectionIcon: {
      width: 42,
      height: 42,
      borderRadius: 16,
      backgroundColor: theme.colors.surfaceAlt,
      alignItems: 'center',
      justifyContent: 'center',
    },
    sectionCopy: {
      flex: 1,
      gap: 4,
    },
    sectionTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    sectionSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
  });

const styles = createStyles(theme);

/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const ProfileRow = React.memo(ProfileRowComponent);
