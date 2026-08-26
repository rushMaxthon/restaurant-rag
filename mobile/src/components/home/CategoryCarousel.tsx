import React from 'react';
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
  type ListRenderItem,
} from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { HomeCategory } from '@/data/homeCategories';

interface CategoryCarouselProps {
  categories: HomeCategory[];
  selectedCategory: string;
  onSelectCategory: (value: string) => void;
}

function CategoryCarouselComponent({
  categories,
  selectedCategory,
  onSelectCategory,
}: CategoryCarouselProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const renderCategory = React.useCallback<ListRenderItem<HomeCategory>>(
    ({ item }) => {
      const active = item.label === selectedCategory;
      return (
        <Pressable
          onPress={() => onSelectCategory(item.label)}
          style={[styles.card, active ? styles.cardActive : null]}
        >
          <View
            style={[styles.iconWrap, active ? styles.iconWrapActive : null]}
          >
            <Icon
              color={active ? theme.colors.white : theme.colors.primary}
              name={item.icon}
              size={18}
            />
          </View>
          <Text style={[styles.label, active ? styles.labelActive : null]}>
            {item.label}
          </Text>
        </Pressable>
      );
    },
    [onSelectCategory, selectedCategory, styles, theme],
  );

  return (
    <FlatList
      contentContainerStyle={styles.list}
      data={categories}
      horizontal
      keyExtractor={item => item.id}
      renderItem={renderCategory}
      showsHorizontalScrollIndicator={false}
    />
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    list: {
      paddingRight: theme.spacing.sm,
      gap: 10,
    },
    card: {
      width: 76,
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      paddingVertical: 11,
      paddingHorizontal: 8,
      alignItems: 'center',
      gap: 8,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    cardActive: {
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.primarySoft : theme.tone('#FFF2EB'),
      borderColor: theme.colors.primary,
    },
    iconWrap: {
      width: 34,
      height: 34,
      borderRadius: 17,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    iconWrapActive: {
      backgroundColor: theme.colors.primary,
    },
    label: {
      color: theme.colors.text,
      fontWeight: '700',
      fontSize: 11,
      textAlign: 'center',
    },
    labelActive: {
      color: theme.colors.primary,
    },
  });


/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const CategoryCarousel = React.memo(CategoryCarouselComponent);
