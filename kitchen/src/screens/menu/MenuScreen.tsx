import React, { useCallback, useMemo, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, SectionList, Text, View } from 'react-native';
import { useTheme, useThemedStyles } from '@/theme';
import type { DishStockChange, KitchenMenuItem, SizeStockChange } from '@/types/app';
import { ScreenContainer } from '@components/ScreenContainer';
import { Icon } from '@components/Icon';
import { SearchField } from '@components/SearchField';
import { Skeleton } from '@components/Skeleton';
import { StateView } from '@components/StateView';
import { MenuStockRow } from '@components/menu/MenuStockRow';
import { StockEditorSheet } from '@components/menu/StockEditorSheet';
import { useBoardScope, useSession } from '@hooks/useAppStore';
import { useKitchenMenu } from '@hooks/useKitchenMenu';
import { useRestaurant } from '@hooks/useRestaurant';
import useNavigationHook from '@navigation/hooks/useNavigation';
import {
  MENU_FILTERS,
  backInStockNeedsCount,
  matchesMenuFilter,
  menuSummary,
  sectionsOf,
  type MenuFilter,
} from '@utils/menuStock';
import { createStyles } from './styles';

const keyOf = (item: KitchenMenuItem) => item.id;

// The kitchen's side of the menu: what is in stock right now. What is ON the
// menu, and at what price, stays the owner's — a dish they hid is listed (so a
// cook knows why it is missing) but cannot be shown again from here.
const MenuScreen = () => {
  const styles = useThemedStyles(createStyles);
  const { colors } = useTheme();
  const navigation = useNavigationHook();
  const session = useSession();
  const scope = useBoardScope();
  const restaurant = useRestaurant(scope.restaurantId);
  const menu = useKitchenMenu(session?.token ?? null, scope);
  const { updateDish, updateSize } = menu;

  const [filter, setFilter] = useState<MenuFilter>('ALL');
  const [search, setSearch] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  // Sections a cook folded away. Kept across polls; reset with the screen.
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(new Set());

  const branches = restaurant?.locations ?? [];
  const branchName =
    branches.find(location => location.id === scope.locationId)?.branch_name ??
    (scope.locationId ? null : 'All branches');
  const showBranch = scope.locationId === null && branches.length > 1;

  const visible = useMemo(
    () => menu.items.filter(item => matchesMenuFilter(item, filter, search)),
    [menu.items, filter, search],
  );
  const sections = useMemo(
    () =>
      sectionsOf(visible, showBranch).map(section => ({
        ...section,
        count: section.data.length,
        data: collapsed.has(section.title) ? [] : section.data,
      })),
    [visible, showBranch, collapsed],
  );
  const summary = useMemo(() => menuSummary(menu.items), [menu.items]);
  const editing = editingId ? menu.items.find(item => item.id === editingId) ?? null : null;

  const toggleSection = useCallback((title: string) => {
    setCollapsed(current => {
      const next = new Set(current);
      if (next.has(title)) {
        next.delete(title);
      } else {
        next.add(title);
      }
      return next;
    });
  }, []);

  const onEdit = useCallback((item: KitchenMenuItem) => setEditingId(item.id), []);
  const onToggle = useCallback(
    (item: KitchenMenuItem) => {
      if (!item.out_of_stock) {
        updateDish(item, { out_of_stock: true });
      } else if (backInStockNeedsCount(item)) {
        // Switching it back on would still leave it sold out at zero: ask
        // for a count rather than pretend.
        setEditingId(item.id);
      } else {
        updateDish(item, { out_of_stock: false });
      }
    },
    [updateDish],
  );
  const onStep = useCallback(
    (item: KitchenMenuItem, delta: number) => {
      if (item.stock_quantity === null) {
        return;
      }
      updateDish(item, { stock_quantity: Math.max(0, item.stock_quantity + delta) });
    },
    [updateDish],
  );
  const onSave = useCallback(
    async (item: KitchenMenuItem, dish: DishStockChange, sizes: { sizeId: string; change: SizeStockChange }[]) => {
      if (Object.keys(dish).length && !(await updateDish(item, dish))) {
        return false;
      }
      for (const { sizeId, change } of sizes) {
        if (!(await updateSize(item, sizeId, change))) {
          return false;
        }
      }
      return true;
    },
    [updateDish, updateSize],
  );

  const renderItem = useCallback(
    ({ item, index, section }: { item: KitchenMenuItem; index: number; section: { data: KitchenMenuItem[] } }) => (
      <View
        style={[
          styles.column,
          styles.group,
          index === 0 && styles.groupFirst,
          index === section.data.length - 1 && styles.groupLast,
        ]}>
        <MenuStockRow
          item={item}
          first={index === 0}
          pending={menu.pending.has(item.id)}
          error={menu.errors[item.id] ?? null}
          showBranch={false}
          onToggle={onToggle}
          onEdit={onEdit}
        />
      </View>
    ),
    [styles, menu.pending, menu.errors, onToggle, onEdit],
  );

  const renderSectionHeader = useCallback(
    ({ section }: { section: { title: string; count: number } }) => {
      const folded = collapsed.has(section.title);
      return (
        <Pressable
          testID={`menu-section-${section.title}`}
          onPress={() => toggleSection(section.title)}
          accessibilityRole="button"
          accessibilityState={{ expanded: !folded }}
          accessibilityLabel={`${section.title}, ${section.count} items. ${folded ? 'Show' : 'Hide'}.`}
          style={[styles.sectionHead, styles.column]}>
          <Text style={styles.sectionTitle}>{section.title}</Text>
          <Text style={styles.sectionCount}>
            {section.count} {section.count === 1 ? 'item' : 'items'}
          </Text>
          <Icon name={folded ? 'chevron-forward' : 'chevron-down'} size={18} color={colors.textMuted} />
        </Pressable>
      );
    },
    [collapsed, toggleSection, styles, colors.textMuted],
  );

  const empty = () => {
    if (menu.loading) {
      return (
        <View style={[styles.skeletons, styles.column]}>
          {[0, 1, 2, 3, 4].map(key => (
            <Skeleton key={key} height={64} radius={12} />
          ))}
        </View>
      );
    }
    if (menu.error) {
      return (
        <StateView
          icon="cloud-offline-outline"
          tone="danger"
          title="Couldn’t load the menu"
          body={menu.error}
          actionLabel="Try again"
          onAction={() => {
            menu.retry();
          }}
        />
      );
    }
    if (menu.items.length === 0) {
      return (
        <StateView
          testID="menu-empty"
          icon="fast-food-outline"
          title="No dishes on this menu yet"
          body="Dishes are added by the restaurant owner in the admin panel."
        />
      );
    }
    return (
      <StateView
        testID="menu-no-match"
        icon="search"
        title="Nothing matches"
        body="Try another filter or clear the search."
      />
    );
  };

  const stat = (testID: string, value: number, label: string, ink: string, soft: string) => (
    <View
      testID={testID}
      accessible
      accessibilityLabel={`${value} ${label}`}
      style={[styles.stat, { backgroundColor: value ? soft : colors.surface, borderColor: value ? ink : colors.border }]}>
      <Text style={[styles.statValue, { color: value ? ink : colors.text }]}>{value}</Text>
      <Text style={[styles.statLabel, { color: value ? ink : colors.textMuted }]}>{label}</Text>
    </View>
  );

  const header = (
    <View style={styles.column}>
      <View style={styles.header}>
        <View style={styles.headerText}>
          {branchName ? <Text style={styles.overline}>{branchName}</Text> : null}
          <Text accessibilityRole="header" style={styles.title}>
            Menu &amp; stock
          </Text>
          <Text style={styles.subtitle}>Keep your live menu accurate during service.</Text>
        </View>
        {/* The branch picker lives in Settings; only accounts that can pick
            a branch are offered the way there. */}
        {scope.canChooseBranch ? (
          <Pressable
            testID="menu-branch"
            onPress={() => navigation.navigate('SettingsScreen')}
            accessibilityRole="button"
            accessibilityLabel={`Branch: ${branchName ?? 'choose'}. Change branch.`}
            style={({ pressed }) => [styles.branchButton, pressed && { opacity: 0.7 }]}>
            <Icon name="storefront-outline" size={20} color={colors.text} />
            <Icon name="chevron-forward" size={14} color={colors.textMuted} />
          </Pressable>
        ) : null}
      </View>

      <View style={styles.stats}>
        {stat('menu-stat-out', summary.out, 'Out of stock', colors.danger, colors.dangerSoft)}
        {stat('menu-stat-low', summary.low, 'Running low', colors.warning, colors.warningSoft)}
        {stat('menu-stat-hidden', summary.hidden, 'Hidden', colors.textMuted, colors.surfaceMuted)}
      </View>

      <View style={styles.searchCard}>
        <SearchField
          testID="menu-search"
          value={search}
          onChangeText={setSearch}
          placeholder="Search dishes"
          accessibilityLabel="Search dishes"
        />
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
          {MENU_FILTERS.map(entry => {
            const active = entry.key === filter;
            return (
              <Pressable
                key={entry.key}
                testID={`menu-filter-${entry.key}`}
                onPress={() => setFilter(entry.key)}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                style={[
                  styles.chip,
                  {
                    backgroundColor: active ? colors.text : colors.surface,
                    borderColor: active ? colors.text : colors.border,
                  },
                ]}>
                <Text style={[styles.chipText, { color: active ? colors.surface : colors.text }]}>{entry.label}</Text>
              </Pressable>
            );
          })}
        </ScrollView>
      </View>
    </View>
  );

  return (
    <ScreenContainer>
      <SectionList
        sections={sections}
        keyExtractor={keyOf}
        renderItem={renderItem}
        renderSectionHeader={renderSectionHeader}
        ListHeaderComponent={header}
        ListEmptyComponent={empty}
        contentContainerStyle={styles.content}
        stickySectionHeadersEnabled={false}
        initialNumToRender={20}
        windowSize={9}
        keyboardShouldPersistTaps="handled"
        refreshControl={
          <RefreshControl
            refreshing={menu.refreshing}
            onRefresh={() => {
              menu.refresh();
            }}
            tintColor={colors.textMuted}
          />
        }
      />

      <StockEditorSheet
        item={editing}
        pending={editing ? menu.pending.has(editing.id) : false}
        error={editing ? menu.errors[editing.id] ?? null : null}
        onClose={() => setEditingId(null)}
        onStep={onStep}
        onSave={onSave}
      />
    </ScreenContainer>
  );
};

export default MenuScreen;
