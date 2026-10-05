import React from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import type { BoardColumn } from '@/data/boardColumns';
import type { KitchenOrder } from '@/types/app';
import type { ColumnState } from '@hooks/useBoard';
import { Icon } from '@components/Icon';
import { Skeleton } from '@components/Skeleton';
import { StateView } from '@components/StateView';
import { TicketCard } from '@components/board/TicketCard';

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

// One stage's tickets with every state that stage can be in: first load
// (skeletons), empty (calm), filtered to nothing, failed, and overflowing
// the page (says the number, never "and more").
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

  const empty = () => {
    if (state.loading) {
      return (
        <View style={styles.skeletons}>
          <Skeleton height={210} />
          <Skeleton height={170} />
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
      keyExtractor={order => order.id}
      numColumns={numColumns}
      columnWrapperStyle={numColumns > 1 ? styles.columnWrapper : undefined}
      contentContainerStyle={styles.content}
      ItemSeparatorComponent={numColumns > 1 ? null : Separator}
      renderItem={({ item }) => (
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
      )}
      ListEmptyComponent={empty}
      ListFooterComponent={
        state.hidden > 0 ? (
          <View
            accessibilityRole="alert"
            style={[styles.overflow, { backgroundColor: colors.warningSoft, borderColor: colors.warning }]}>
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
  content: { padding: 12, paddingBottom: 32, flexGrow: 1 },
  columnWrapper: { gap: 12 },
  cell: { flex: 1, marginBottom: 12 },
  separator: { height: 12 },
  skeletons: { gap: 12 },
  overflow: {
    flexDirection: 'row',
    gap: 10,
    borderWidth: 1,
    borderRadius: 12,
    padding: 12,
    marginTop: 12,
  },
  overflowText: { flex: 1, fontSize: 14, fontWeight: '600', lineHeight: 20 },
});
