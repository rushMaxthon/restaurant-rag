import React, { useCallback } from 'react';
import {
  FlatList,
  Platform,
  RefreshControl,
  StyleSheet,
  Text,
  View,
} from 'react-native';
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
  // "New orders · 2 tickets on this board" above the list — for the phone,
  // where the stage tabs are the only other sign of which stage this is.
  heading?: boolean;
  // Everything above the tickets on a phone (top bar, title, tabs, search,
  // filters, numbers), so the whole screen scrolls as one rather than only
  // the tickets under a fixed block.
  header?: React.ReactNode;
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
  heading = false,
  header,
  branchNameOf,
  onRefresh,
  onAdvance,
  onOpen,
}: TicketListProps) => {
  const theme = useTheme();
  const { colors } = theme;
  const stageColor = theme.status[column.status];

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
      ListHeaderComponent={
        <>
          {header ? <View style={styles.screenHeader}>{header}</View> : null}
          {heading ? (
            <View style={styles.heading}>
              <View style={styles.headingText}>
                <Text
                  accessibilityRole="header"
                  style={[styles.headingTitle, { color: colors.text }]}
                >
                  {column.title} orders
                </Text>
                <Text
                  style={[styles.headingCount, { color: colors.textMuted }]}
                >
                  {visible.length} {visible.length === 1 ? 'ticket' : 'tickets'}{' '}
                  on this board
                </Text>
              </View>
              <View
                style={[
                  styles.stagePill,
                  { backgroundColor: colors.surface, borderColor: stageColor },
                ]}
              >
                <View
                  style={[styles.stageDot, { backgroundColor: stageColor }]}
                />
                <Text style={[styles.stagePillText, { color: colors.text }]}>
                  {column.title}
                </Text>
              </View>
            </View>
          ) : null}
        </>
      }
      ListEmptyComponent={empty}
      // The search box scrolls with the list on a phone: a tap on a chip or
      // a ticket while typing should land, not just close the keyboard.
      keyboardShouldPersistTaps="handled"
      ListFooterComponent={
        state.hidden > 0 ? (
          <View
            accessibilityRole="alert"
            style={[
              styles.overflow,
              {
                backgroundColor: colors.warningSoft,
                borderLeftColor: colors.warning,
              },
            ]}
          >
            <Icon name="alert-circle" size={18} color={colors.warning} />
            <Text style={[styles.overflowText, { color: colors.text }]}>
              {state.hidden} more{' '}
              {state.hidden === 1 ? 'ticket is' : 'tickets are'} waiting and not
              shown here. Work through these first, or ask your manager.
            </Text>
          </View>
        ) : null
      }
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={onRefresh}
          tintColor={colors.textMuted}
        />
      }
    />
  );
};

const Separator = () => <View style={styles.separator} />;

const styles = StyleSheet.create({
  // The screen's own header runs edge to edge; the list's padding is for
  // the tickets.
  screenHeader: {
    marginHorizontal: -space.md,
    marginTop: -space.md,
    marginBottom: space.md,
  },
  heading: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: space.md,
    paddingBottom: space.md,
  },
  headingText: { flex: 1, gap: 2 },
  headingTitle: { fontSize: 20, fontWeight: '800' },
  headingCount: { fontSize: 13, fontWeight: '500' },
  stagePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderWidth: 1,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  stageDot: { width: 8, height: 8, borderRadius: 4 },
  stagePillText: { fontSize: 12, fontWeight: '800' },
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
