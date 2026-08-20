import React from 'react';
import { StyleSheet, View } from 'react-native';
import { SkeletonBlock } from '@components/SkeletonBlock';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

export function HomeSkeleton(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <View style={styles.wrap}>
      <SkeletonBlock borderRadius={28} height={220} />
      <SkeletonBlock borderRadius={18} height={56} />
      <View style={styles.row}>
        <SkeletonBlock borderRadius={20} height={92} />
        <SkeletonBlock borderRadius={20} height={92} />
        <SkeletonBlock borderRadius={20} height={92} />
      </View>
      <SkeletonBlock borderRadius={26} height={170} />
      <View style={styles.row}>
        <SkeletonBlock borderRadius={24} height={280} />
        <SkeletonBlock borderRadius={24} height={280} />
      </View>
      <SkeletonBlock borderRadius={24} height={154} />
      <SkeletonBlock borderRadius={24} height={220} />
      <SkeletonBlock borderRadius={24} height={220} />
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    wrap: {
      gap: theme.spacing.lg,
    },
    row: {
      flexDirection: 'row',
      gap: 12,
    },
  });

const styles = createStyles(theme);
