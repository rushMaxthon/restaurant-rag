import React, { useCallback } from 'react';
import { FlatList, Platform, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { radius, space, useTheme } from '@/theme';
import type { BoardColumn } from '@/data/boardColumns';
import type { KitchenOrder } from '@/types/app';
import type { ColumnState } from '@hooks/useBoard';
import { Icon } from '@components/Icon';
import { StateView } from '@components/StateView';
import { TicketCard } from '@components/board/TicketCard';
import { TicketSkeleton } from '@components/board/TicketSkeleton';

interface TicketListProps {
  column: BoardColumn;
  state: ColumnState;
  visible: KitchenOrder[];
  filtering: boolean;
  now: Date;
  fresh: ReadonlySet<string>;
  pending: ReadonlySet<string>;
  errors: Readonly<Record<string, string>>;
  refreshing: boolean;
  // Two tickets side by side — a tablet in portrait.
  numColumns?: number;
  branchNameOf: (order: KitchenOrder) => string | null;
  onRefresh: () => void;
  onAdvance: (order: KitchenOrder) => void;
  onOpen: (order: KitchenOrder) => void;
}

const keyOf = (order: KitchenOrder) => order.id;

// One stage's tickets with every state that stage can be in: first load
// (ticket-shaped skeletons), empty (calm), filtered to nothing, failed, and
// overflowing the page (says the number, never "and more").
export const TicketList = ({
  column,
  state,
  visible,
  filtering,
  now,
  fresh,
  pending,
  errors,
  refreshing,
  numColumns = 1,
  branchNameOf,
  onRefresh,
  onAdvance,
  onOpen,
}: TicketListProps) => {
  const { colors } = useTheme();

  const renderItem = useCallback(
    ({ item }: { item: KitchenOrder }) => (
      <View style={numColumns > 1 ? styles.cell : null}>
        <TicketCard
          order={item}
          now={now}
          fresh={fresh.has(item.id)}
          pending={pending.has(item.id)}
          error={errors[item.id] ?? null}
          branchName={branchNameOf(item)}
          onAdvance={onAdvance}
          onOpen={onOpen}
        />
      </View>
    ),
    [numColumns, now, fresh, pending, errors, branchNameOf, onAdvance, onOpen],
  );

  const empty = () => {
    if (state.loading) {
      return (
        <View style={styles.skeletons}>
          <TicketSkeleton />
          <TicketSkeleton />
        </View>
      );
    }
    if (state.failed && state.orders.length === 0) {
      return (
        <StateView
          compact
          icon="cloud-offline-outline"
          tone="danger"
          title="Couldn’t load this stage"
          body="Pull down to try again. Other stages are unaffected."
        />
      );
    }
    if (filtering) {
      return (
        <StateView
          compact
          icon="file-tray-outline"
          title="Nothing matches"
          body="Try another filter or clear the search."
        />
      );
    }
    return (
      <StateView
        compact
        testID={`empty-${column.status}`}
        icon="checkmark-done"
        tone="calm"
        title={column.emptyTitle}
        body={column.emptyBody}
      />
    );
  };

  return (
    <FlatList
      key={numColumns}
      data={visible}
      keyExtractor={keyOf}
      numColumns={numColumns}
      columnWrapperStyle={numColumns > 1 ? styles.columnWrapper : undefined}
      contentContainerStyle={styles.content}
      ItemSeparatorComponent={numColumns > 1 ? null : Separator}
      renderItem={renderItem}
      // Tickets are tall: a few cover the screen, so render in small batches
      // and keep a modest window either side of it.
      initialNumToRender={4}
      maxToRenderPerBatch={4}
      windowSize={7}
      // Detaching off-screen rows is a clear win on Android and buggy on iOS.
      removeClippedSubviews={Platform.OS === 'android'}
      ListEmptyComponent={empty}
      ListFooterComponent={
        state.hidden > 0 ? (
          <View
            accessibilityRole="alert"
            style={[styles.overflow, { backgroundColor: colors.warningSoft, borderLeftColor: colors.warning }]}>
            <Icon name="alert-circle" size={18} color={colors.warning} />
            <Text style={[styles.overflowText, { color: colors.text }]}>
              {state.hidden} more {state.hidden === 1 ? 'ticket is' : 'tickets are'} waiting and not
              shown here. Work through these first, or ask your manager.
            </Text>
          </View>
        ) : null
      }
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.textMuted} />
      }
    />
  );
};

const Separator = () => <View style={styles.separator} />;

const styles = StyleSheet.create({
  content: { padding: space.md, paddingBottom: space.xxxl, flexGrow: 1 },
  columnWrapper: { gap: space.md },
  cell: { flex: 1, marginBottom: space.md },
  separator: { height: space.md },
  skeletons: { gap: space.md },
  overflow: {
    flexDirection: 'row',
    gap: 10,
    borderLeftWidth: 4,
    borderRadius: radius.md,
    padding: space.md,
    marginTop: space.md,
  },
  overflowText: { flex: 1, fontSize: 14, fontWeight: '600', lineHeight: 20 },
});
