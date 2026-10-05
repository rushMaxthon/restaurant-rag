import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { radius, space, type, useTheme } from '@/theme';
import { Icon } from '@components/Icon';

interface ScreenHeaderProps {
  title: string;
  subtitle?: string;
  onBack?: () => void;
  right?: React.ReactNode;
}

// The bar on every screen but the board. A raised surface with a hairline,
// so content scrolling beneath it reads as beneath. The back target is a full
// 48pt square: it is reached for with a wet or gloved hand.
export const ScreenHeader = ({ title, subtitle, onBack, right }: ScreenHeaderProps) => {
  const { colors } = useTheme();
  return (
    <View style={[styles.row, { backgroundColor: colors.surface, borderBottomColor: colors.border }]}>
      {onBack ? (
        <Pressable
          testID="header-back"
          onPress={onBack}
          hitSlop={6}
          accessibilityRole="button"
          accessibilityLabel="Back"
          style={({ pressed }) => [
            styles.back,
            { backgroundColor: colors.surfaceMuted, borderColor: colors.border },
            pressed && styles.pressed,
          ]}>
          <Icon name="arrow-back" size={24} color={colors.text} />
        </Pressable>
      ) : null}
      <View style={styles.titles}>
        <Text accessibilityRole="header" numberOfLines={1} style={[styles.title, { color: colors.text }]}>
          {title}
        </Text>
        {subtitle ? (
          <Text numberOfLines={1} style={[styles.subtitle, { color: colors.textMuted }]}>
            {subtitle}
          </Text>
        ) : null}
      </View>
      {right}
    </View>
  );
};

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    minHeight: 72,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  back: {
    width: 48,
    height: 48,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  pressed: { opacity: 0.7 },
  titles: { flex: 1, minWidth: 0 },
  title: type.title,
  subtitle: { ...type.caption, marginTop: 1 },
});
