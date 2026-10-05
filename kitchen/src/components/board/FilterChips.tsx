import React from 'react';
import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { useTheme } from '@/theme';
import { BOARD_FILTERS, type BoardFilter } from '@/data/boardFilters';

export const FilterChips = ({
  value,
  onChange,
}: {
  value: BoardFilter;
  onChange: (filter: BoardFilter) => void;
}) => {
  const { colors } = useTheme();
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      style={styles.strip}
      contentContainerStyle={styles.row}>
      {BOARD_FILTERS.map(filter => {
        const active = filter.key === value;
        return (
          <Pressable
            key={filter.key}
            testID={`filter-${filter.key}`}
            onPress={() => onChange(filter.key)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            style={[
              styles.chip,
              {
                backgroundColor: active ? colors.text : colors.surfaceMuted,
                borderColor: active ? colors.text : colors.border,
              },
            ]}>
            <Text style={[styles.label, { color: active ? colors.surface : colors.text }]}>
              {filter.label}
            </Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  strip: { flexGrow: 0 },
  row: { gap: 8, alignItems: 'center' },
  chip: {
    height: 44,
    borderRadius: 22,
    borderWidth: 1,
    paddingHorizontal: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  label: { fontSize: 14, fontWeight: '700' },
});
