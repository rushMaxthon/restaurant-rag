import React, { memo } from 'react';
import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { radius, useTheme } from '@/theme';
import { BOARD_FILTERS, type BoardFilter } from '@/data/boardFilters';
import { Icon, type IconName } from '@components/Icon';

const FILTER_ICONS: Record<BoardFilter, IconName | null> = {
  ALL: null,
  DELIVERY: 'bicycle',
  PICKUP: 'bag-handle-outline',
  PRIORITY: 'flame',
};

// `compact` (phones) drops the icons and tightens the padding so all four
// chips fit beside the search button without scrolling.
const FilterChipsComponent = ({
  value,
  onChange,
  compact = false,
}: {
  value: BoardFilter;
  onChange: (filter: BoardFilter) => void;
  compact?: boolean;
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
        const icon = compact ? null : FILTER_ICONS[filter.key];
        const ink = active ? colors.surface : colors.text;
        return (
          <Pressable
            key={filter.key}
            testID={`filter-${filter.key}`}
            onPress={() => onChange(filter.key)}
            accessibilityRole="button"
            accessibilityState={{ selected: active }}
            style={[
              styles.chip,
              compact && styles.chipCompact,
              {
                backgroundColor: active ? colors.text : colors.surface,
                borderColor: active ? colors.text : colors.border,
              },
            ]}>
            {icon ? <Icon name={icon} size={15} color={ink} /> : null}
            <Text style={[styles.label, { color: ink }]}>{filter.label}</Text>
          </Pressable>
        );
      })}
    </ScrollView>
  );
};

export const FilterChips = memo(FilterChipsComponent);

const styles = StyleSheet.create({
  strip: { flexGrow: 0 },
  row: { gap: 8, alignItems: 'center' },
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    height: 44,
    borderRadius: radius.pill,
    borderWidth: 1,
    paddingHorizontal: 14,
  },
  chipCompact: { paddingHorizontal: 12 },
  label: { fontSize: 14, fontWeight: '700' },
});
