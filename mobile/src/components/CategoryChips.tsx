import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface CategoryChipsProps {
  categories: string[];
  activeCategory: string;
  onSelect: (category: string) => void;
}

function CategoryChipsComponent({
  categories,
  activeCategory,
  onSelect,
}: CategoryChipsProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      contentContainerStyle={styles.content}
      style={styles.scroll}
    >
      {categories.map(category => {
        const active = activeCategory === category;
        return (
          <Pressable
            key={category}
            onPress={() => onSelect(category)}
            style={[styles.chip, active ? styles.chipActive : null]}
          >
            <Text style={[styles.label, active ? styles.labelActive : null]}>
              {category}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    scroll: {
      flexGrow: 0,
    },
    content: {
      paddingHorizontal: theme.spacing.screen,
      paddingVertical: 6,
      gap: 10,
    },
    chip: {
      minHeight: 36,
      borderRadius: 20,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 14,
      paddingVertical: 6,
      backgroundColor: theme.colors.surfaceRaised,
      alignItems: 'center',
      justifyContent: 'center',
    },
    chipActive: {
      backgroundColor: theme.colors.primary,
      borderColor: theme.colors.primary,
    },
    label: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '700',
    },
    labelActive: {
      color: theme.colors.white,
    },
  });

const styles = createStyles(theme);

/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const CategoryChips = React.memo(CategoryChipsComponent);
