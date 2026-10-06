import React, { useCallback, useMemo, useState } from 'react';
import { ScrollView, Text, View, useWindowDimensions } from 'react-native';
import { BOARD_COLUMNS } from '@/data/boardColumns';
import type { BoardFilter } from '@/data/boardFilters';
import type { KitchenOrder, LiveStatus } from '@/types/app';
import { inkOn } from '@/themePalette';
import { useTheme, useThemedStyles } from '@/theme';
import { ScreenContainer } from '@components/ScreenContainer';
import { freshnessOf } from '@components/LiveIndicator';
import { SearchField } from '@components/SearchField';
import { StateView } from '@components/StateView';
import { BoardHeader } from '@components/board/BoardHeader';
import { FilterChips } from '@components/board/FilterChips';
import { MetricsStrip } from '@components/board/MetricsStrip';
import { StageTabs } from '@components/board/StageTabs';
import { TicketList } from '@components/board/TicketList';
import { useRealtimeStatus } from '@components/realtime/RealtimeProvider';
import { useAdvanceOrder } from '@hooks/useAdvanceOrder';
import {
  useAppActions,
  useBoardScope,
  usePreferences,
  useSession,
} from '@hooks/useAppStore';
import { useBoard } from '@hooks/useBoard';
import { useNewOrderAlerts } from '@hooks/useNewOrderAlerts';
import { useNow } from '@hooks/useNow';
import { useRestaurant } from '@hooks/useRestaurant';
import useNavigationHook from '@navigation/hooks/useNavigation';
import { urgencyOf } from '@utils/board';
import { boardMetrics, matchesFilter } from '@utils/metrics';
import { pollIntervalFor } from '@utils/realtime';
import { COLUMNS_MIN_WIDTH, TWO_UP_MIN_WIDTH, createStyles } from './styles';

const perStage = <T,>(
  value: (status: LiveStatus) => T,
): Record<LiveStatus, T> => ({
  PLACED: value('PLACED'),
  ACCEPTED: value('ACCEPTED'),
  PREPARING: value('PREPARING'),
  OUT_FOR_DELIVERY: value('OUT_FOR_DELIVERY'),
});

const BoardScreen = () => {
  const session = useSession();
  const { signOut } = useAppActions();

  // An ADMIN has no restaurant of their own and the board cannot guess one.
  // Saying so beats four empty columns that look like a quiet service.
  if (session && !session.restaurantId) {
    return (
      <ScreenContainer>
        <StateView
          testID="no-restaurant"
          icon="storefront-outline"
          title="No restaurant on this account"
          body="Admin accounts have no kitchen of their own. Sign in with the restaurant’s owner or kitchen account to open its board."
          actionLabel="Switch account"
          onAction={() => signOut()}
        />
      </ScreenContainer>
    );
  }
  return <LiveBoard />;
};

const LiveBoard = () => {
  const styles = useThemedStyles(createStyles);
  const theme = useTheme();
  const navigation = useNavigationHook();
  const session = useSession();
  const token = session?.token ?? null;
  const scope = useBoardScope();
  const { soundOn } = usePreferences();
  const { setSoundOn } = useAppActions();
  const realtime = useRealtimeStatus();
  const restaurant = useRestaurant(scope.restaurantId);
  const now = useNow();
  const { width } = useWindowDimensions();
  const wide = width >= COLUMNS_MIN_WIDTH;
  const twoUp = !wide && width >= TWO_UP_MIN_WIDTH;

  const board = useBoard(token, scope, pollIntervalFor(realtime));
  const { advance, pending, errors } = useAdvanceOrder(token, scope);

  const [filter, setFilter] = useState<BoardFilter>('ALL');
  const [search, setSearch] = useState('');
  const [stage, setStage] = useState<LiveStatus>('PLACED');

  // Everything derived from the board is memoised on what it reads, so the
  // memoised header, tabs and tickets below are handed the SAME objects when
  // nothing they show has changed — and skip their render.
  const { columns } = board;
  const allOrders = useMemo(
    () => BOARD_COLUMNS.flatMap(column => columns[column.status].orders),
    [columns],
  );
  const scopeKey = `${scope.restaurantId}:${scope.locationId}`;
  const fresh = useNewOrderAlerts(allOrders, board.loading, soundOn, scopeKey);

  const metrics = useMemo(() => boardMetrics(allOrders, now), [allOrders, now]);
  const counts = useMemo(
    () => perStage(status => columns[status].orders.length),
    [columns],
  );
  const late = useMemo(
    () =>
      perStage(status =>
        columns[status].orders.some(order => urgencyOf(order, now) === 'late'),
      ),
    [columns, now],
  );
  const arrived = useMemo(
    () =>
      perStage(status =>
        columns[status].orders.some(order => fresh.has(order.id)),
      ),
    [columns, fresh],
  );
  const visible = useMemo(
    () =>
      perStage(status => {
        const orders = columns[status].orders;
        return filter === 'ALL' && !search.trim()
          ? orders
          : orders.filter(order => matchesFilter(order, filter, search, now));
      }),
    [columns, filter, search, now],
  );
  const filtering = filter !== 'ALL' || search.trim() !== '';

  const branches = restaurant?.locations ?? [];
  const currentBranch =
    branches.find(location => location.id === scope.locationId) ?? null;
  const branchName =
    currentBranch?.branch_name ?? (scope.locationId ? null : 'All branches');
  // Each ticket names its branch only while the board spans several.
  const showBranchOnTickets = scope.locationId === null && branches.length > 1;
  const branchNameOf = useCallback(
    (order: KitchenOrder) =>
      showBranchOnTickets
        ? order.restaurant_location?.branch_name ?? null
        : null,
    [showBranchOnTickets],
  );

  const openOrder = useCallback(
    (order: KitchenOrder) =>
      navigation.navigate('OrderDetailScreen', { orderId: order.id, order }),
    [navigation],
  );
  const onAdvance = useCallback(
    (order: KitchenOrder) => {
      advance(order);
    },
    [advance],
  );
  const onToggleSound = useCallback(
    () => setSoundOn(!soundOn),
    [setSoundOn, soundOn],
  );
  const onOpenHistory = useCallback(
    () => navigation.navigate('OrderHistoryScreen'),
    [navigation],
  );
  const onOpenSettings = useCallback(
    () => navigation.navigate('SettingsScreen'),
    [navigation],
  );
  const { refresh } = board;
  const onRefresh = useCallback(() => {
    refresh();
  }, [refresh]);

  const headerProps = {
    wide,
    restaurantName: restaurant?.name ?? null,
    branchName,
    isOpen: currentBranch?.is_open,
    freshness: freshnessOf(realtime, board.stale),
    now,
    soundOn,
    onToggleSound,
    onOpenHistory,
    onOpenSettings,
  };
  const header = <BoardHeader {...headerProps} />;

  // Every column failed and there is nothing to show. Four columns of
  // nothing would read as a quiet service; this says what is wrong.
  if (board.down) {
    return (
      <ScreenContainer>
        <ScrollView contentContainerStyle={styles.downScroll}>
          {header}
          <StateView
            testID="board-down"
            icon="cloud-offline-outline"
            tone="danger"
            title="The board isn’t updating"
            body="This tablet can’t reach the server. Orders already placed are safe — the board will catch up as soon as the connection is back."
            actionLabel="Try again"
            onAction={onRefresh}
          />
        </ScrollView>
      </ScreenContainer>
    );
  }

  const listFor = (
    status: LiveStatus,
    numColumns = 1,
    heading = false,
    top?: React.ReactNode,
  ) => {
    const column = BOARD_COLUMNS.find(entry => entry.status === status)!;
    return (
      <TicketList
        column={column}
        state={columns[status]}
        visible={visible[status]}
        filtering={filtering}
        now={now}
        fresh={fresh}
        pending={pending}
        errors={errors}
        refreshing={board.refreshing}
        numColumns={numColumns}
        heading={heading}
        header={top}
        branchNameOf={branchNameOf}
        onRefresh={onRefresh}
        onAdvance={onAdvance}
        onOpen={openOrder}
      />
    );
  };

  if (wide) {
    return (
      <ScreenContainer>
        {header}
        <View style={styles.wideTools}>
          <View style={styles.search}>
            <SearchField
              testID="board-search"
              value={search}
              onChangeText={setSearch}
              placeholder="Search order or guest"
              accessibilityLabel="Search by order number or guest name"
            />
          </View>
          <View style={styles.chips}>
            <FilterChips value={filter} onChange={setFilter} compact />
          </View>
          <View style={styles.wideStats}>
            <MetricsStrip metrics={metrics} />
          </View>
        </View>
        <View style={styles.columns}>
          {BOARD_COLUMNS.map(column => {
            const stageColor = theme.status[column.status];
            return (
              <View key={column.status} style={styles.column}>
                <View style={styles.columnHead}>
                  <View
                    style={[styles.columnDot, { backgroundColor: stageColor }]}
                  />
                  <Text accessibilityRole="header" style={styles.columnTitle}>
                    {column.title}
                  </Text>
                  <View
                    style={[
                      styles.columnCount,
                      { backgroundColor: stageColor },
                    ]}
                  >
                    <Text
                      style={[
                        styles.columnCountText,
                        { color: inkOn(stageColor) },
                      ]}
                    >
                      {visible[column.status].length}
                    </Text>
                  </View>
                </View>
                {listFor(column.status)}
              </View>
            );
          })}
        </View>
      </ScreenContainer>
    );
  }

  // Phone: the top bar stays put; everything under it — title, tabs, search,
  // filters, numbers and tickets — scrolls as one. That section is the ticket
  // list's own header, so the list stays virtualised however long the queue.
  const top = (
    <>
      <BoardHeader {...headerProps} part="title" />
      <View style={styles.phoneTools}>
        <StageTabs
          value={stage}
          onChange={setStage}
          counts={counts}
          late={late}
          arrived={arrived}
        />
        <SearchField
          testID="board-search"
          value={search}
          onChangeText={setSearch}
          placeholder="Search order or guest"
          accessibilityLabel="Search by order number or guest name"
        />
        <FilterChips value={filter} onChange={setFilter} compact />
        <MetricsStrip metrics={metrics} />
      </View>
    </>
  );

  return (
    <ScreenContainer>
      {/* Fixed: whose kitchen, and the board's tools, always in reach. */}
      <BoardHeader {...headerProps} part="bar" />
      <View style={styles.list}>
        {listFor(stage, twoUp ? 2 : 1, true, top)}
      </View>
    </ScreenContainer>
  );
};

export default BoardScreen;
