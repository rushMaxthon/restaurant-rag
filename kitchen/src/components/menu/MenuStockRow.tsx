import React, { memo } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import { radius, space, useTheme, type AppTheme } from '@/theme';
import type { KitchenMenuItem } from '@/types/app';
import { Icon } from '@components/Icon';
import { backInStockNeedsCount, sizeLabel, stockLabel, stockState, type StockState } from '@utils/menuStock';

interface MenuStockRowProps {
  item: KitchenMenuItem;
  pending: boolean;
  error: string | null;
  showBranch: boolean;
  // The first row of a section has no divider above it.
  first: boolean;
  onToggle: (item: KitchenMenuItem) => void;
  onEdit: (item: KitchenMenuItem) => void;
}

const toneOf = (state: StockState, { colors }: AppTheme) => {
  switch (state) {
    case 'out':
    case 'sold_out':
      return colors.danger;
    case 'low':
      return colors.warning;
    case 'hidden':
      return colors.textMuted;
    default:
      return colors.accent;
  }
};

// The status line: what a customer can do with the dish, then the count.
// "In stock · 18 left", "Running low · 4 left", "Out of stock".
const statusText = (item: KitchenMenuItem, state: StockState): string => {
  switch (state) {
    case 'counted':
      return `In stock · ${item.stock_quantity} left`;
    case 'low':
      return `Running low · ${item.stock_quantity} left`;
    default:
      return stockLabel(item);
  }
};

// One dish in the inventory list: an icon tile, the name, its status and
// details, and the one action a cook reaches for — Mark out or Restock.
// Tapping anywhere else opens the editor (counts, refill, sizes, quick adjust).
const MenuStockRowComponent = ({ item, pending, error, showBranch, first, onToggle, onEdit }: MenuStockRowProps) => {
  const theme = useTheme();
  const { colors } = theme;
  const state = stockState(item);
  const tone = toneOf(state, theme);
  const isOut = item.out_of_stock;
  const toggleLabel = isOut ? (backInStockNeedsCount(item) ? 'Restock…' : 'Back in stock') : 'Mark out of stock';

  const details = [
    ...item.sizes.map(size => `${size.name}: ${sizeLabel(size)}`),
    item.stock_daily_quantity !== null ? `${item.stock_daily_quantity} each morning` : null,
    showBranch ? item.branch_name : null,
  ].filter(Boolean);

  return (
    <View
      testID={`menu-row-${item.id}`}
      style={[styles.row, !first && { borderTopColor: colors.border, borderTopWidth: StyleSheet.hairlineWidth }]}>
      <Pressable
        onPress={() => onEdit(item)}
        accessibilityRole="button"
        accessibilityLabel={`${item.name}, ${stockLabel(item)}. Edit stock.`}
        style={({ pressed }) => [styles.line, pressed && styles.pressed]}>
        <View style={[styles.tile, { backgroundColor: colors.surfaceMuted }]}>
          <Icon
            name={state === 'hidden' ? 'eye-off-outline' : 'cube-outline'}
            size={20}
            color={colors.textMuted}
          />
          <View style={[styles.vegBadge, { backgroundColor: colors.surface }]}>
            <View style={[styles.vegDot, { backgroundColor: item.is_veg ? colors.accent : colors.danger }]} />
          </View>
        </View>

        <View style={styles.text}>
          <Text numberOfLines={1} style={[styles.name, { color: state === 'hidden' ? colors.textMuted : colors.text }]}>
            {item.name}
          </Text>
          <View style={styles.statusRow}>
            <View style={[styles.dot, { backgroundColor: tone }]} />
            <Text numberOfLines={1} style={[styles.status, { color: tone }]}>
              {statusText(item, state)}
            </Text>
            {details.length ? (
              <Text numberOfLines={1} style={[styles.details, { color: colors.textMuted }]}>
                {details.join(' · ')}
              </Text>
            ) : null}
          </View>
        </View>

        <Pressable
          testID={`menu-toggle-${item.id}`}
          onPress={() => onToggle(item)}
          disabled={pending}
          hitSlop={6}
          accessibilityRole="button"
          accessibilityLabel={`${toggleLabel}: ${item.name}`}
          style={({ pressed }) => [
            styles.action,
            isOut
              ? { backgroundColor: colors.accentSoft, borderColor: colors.accentSoft }
              : { backgroundColor: colors.surface, borderColor: colors.danger },
            pressed && styles.pressed,
          ]}>
          {pending ? (
            <ActivityIndicator size="small" color={isOut ? colors.accent : colors.danger} />
          ) : (
            <Text style={[styles.actionText, { color: isOut ? colors.accent : colors.danger }]}>
              {isOut ? 'Restock' : 'Mark out'}
            </Text>
          )}
        </Pressable>
        <Icon name="chevron-forward" size={18} color={colors.textMuted} />
      </Pressable>

      {error ? (
        <View accessibilityRole="alert" style={[styles.error, { backgroundColor: colors.dangerSoft }]}>
          <Icon name="alert-circle" size={14} color={colors.danger} />
          <Text numberOfLines={2} style={[styles.errorText, { color: colors.danger }]}>
            {error}
          </Text>
        </View>
      ) : null}
    </View>
  );
};

export const MenuStockRow = memo(MenuStockRowComponent);

const styles = StyleSheet.create({
  row: {},
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingVertical: 12,
    minHeight: 64,
  },
  pressed: { opacity: 0.6 },
  tile: { width: 40, height: 40, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  vegBadge: {
    position: 'absolute',
    right: -2,
    bottom: -2,
    width: 12,
    height: 12,
    borderRadius: 6,
    alignItems: 'center',
    justifyContent: 'center',
  },
  vegDot: { width: 7, height: 7, borderRadius: 4 },
  text: { flex: 1, minWidth: 0, gap: 3 },
  name: { fontSize: 16, fontWeight: '700' },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  dot: { width: 7, height: 7, borderRadius: 4 },
  status: { fontSize: 13, fontWeight: '700', flexShrink: 0 },
  details: { fontSize: 13, fontWeight: '500', flexShrink: 1, marginLeft: 3 },
  action: {
    minWidth: 82,
    height: 34,
    borderWidth: 1,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.md,
  },
  actionText: { fontSize: 14, fontWeight: '800' },
  error: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginHorizontal: space.lg,
    marginBottom: 10,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  errorText: { flex: 1, fontSize: 12, fontWeight: '700' },
});
