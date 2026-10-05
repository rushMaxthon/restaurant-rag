import React, { useCallback, useMemo, useState } from 'react';
import { Text, View, useWindowDimensions } from 'react-native';
import { BOARD_COLUMNS } from '@/data/boardColumns';
import type { BoardFilter } from '@/data/boardFilters';
import type { KitchenOrder, LiveStatus } from '@/types/app';
import { useTheme, useThemedStyles } from '@/theme';
import { ScreenContainer } from '@components/ScreenContainer';
import { IconButton } from '@components/IconButton';
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
import { useAppActions, useBoardScope, usePreferences, useSession } from '@hooks/useAppStore';
import { useBoard } from '@hooks/useBoard';
import { useNewOrderAlerts } from '@hooks/useNewOrderAlerts';
import { useNow } from '@hooks/useNow';
import { useRestaurant } from '@hooks/useRestaurant';
import useNavigationHook from '@navigation/hooks/useNavigation';
import { formatWait, urgencyOf } from '@utils/board';
import { boardMetrics, matchesFilter } from '@utils/metrics';
import { pollIntervalFor } from '@utils/realtime';
import { COLUMNS_MIN_WIDTH, TWO_UP_MIN_WIDTH, createStyles } from './styles';

const perStage = <T,>(value: (status: LiveStatus) => T): Record<LiveStatus, T> => ({
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
  const [searchOpen, setSearchOpen] = useState(false);
  const [stage, setStage] = useState<LiveStatus>('PLACED');

  const allOrders = useMemo(
    () => BOARD_COLUMNS.flatMap(column => board.columns[column.status].orders),
    [board.columns],
  );
  const scopeKey = `${scope.restaurantId}:${scope.locationId}`;
  const fresh = useNewOrderAlerts(allOrders, board.loading, soundOn, scopeKey);

  const metrics = useMemo(() => boardMetrics(allOrders, now), [allOrders, now]);
  const counts = perStage(status => board.columns[status].orders.length);
  const late = perStage(status =>
    board.columns[status].orders.some(order => urgencyOf(order, now) === 'late'),
  );
  const arrived = perStage(status =>
    board.columns[status].orders.some(order => fresh.has(order.id)),
  );

  const filtering = filter !== 'ALL' || search.trim() !== '';
  const visibleIn = (status: LiveStatus) =>
    board.columns[status].orders.filter(order => matchesFilter(order, filter, search, now));

  const branches = restaurant?.locations ?? [];
  const currentBranch = branches.find(location => location.id === scope.locationId) ?? null;
  const branchName = currentBranch?.branch_name ?? (scope.locationId ? null : 'All branches');
  // Each ticket names its branch only while the board spans several.
  const showBranchOnTickets = scope.locationId === null && branches.length > 1;
  const branchNameOf = useCallback(
    (order: KitchenOrder) =>
      showBranchOnTickets ? order.restaurant_location?.branch_name ?? null : null,
    [showBranchOnTickets],
  );

  const openOrder = useCallback(
    (order: KitchenOrder) =>
      navigation.navigate('OrderDetailScreen', { orderId: order.id, order }),
    [navigation],
  );
  const onAdvance = useCallback((order: KitchenOrder) => { advance(order); }, [advance]);

  const header = (
    <BoardHeader
      wide={wide}
      restaurantName={restaurant?.name ?? null}
      branchName={branchName}
      isOpen={currentBranch?.is_open}
      freshness={freshnessOf(realtime, board.stale)}
      now={now}
      soundOn={soundOn}
      onToggleSound={() => setSoundOn(!soundOn)}
      onOpenHistory={() => navigation.navigate('OrderHistoryScreen')}
      onOpenSettings={() => navigation.navigate('SettingsScreen')}
    />
  );

  // Every column failed and there is nothing to show. Four columns of
  // nothing would read as a quiet service; this says what is wrong.
  if (board.down) {
    return (
      <ScreenContainer>
        {header}
        <StateView
          testID="board-down"
          icon="cloud-offline-outline"
          tone="danger"
          title="The board isn’t updating"
          body="This tablet can’t reach the server. Orders already placed are safe — the board will catch up as soon as the connection is back."
          actionLabel="Try again"
          onAction={() => { board.refresh(); }}
        />
      </ScreenContainer>
    );
  }

  const listFor = (status: LiveStatus, numColumns = 1) => {
    const column = BOARD_COLUMNS.find(entry => entry.status === status)!;
    return (
      <TicketList
        column={column}
        state={board.columns[status]}
        visible={visibleIn(status)}
        filtering={filtering}
        now={now}
        fresh={fresh}
        pending={pending}
        errors={errors}
        refreshing={board.refreshing}
        numColumns={numColumns}
        branchNameOf={branchNameOf}
        onRefresh={() => { board.refresh(); }}
        onAdvance={onAdvance}
        onOpen={openOrder}
      />
    );
  };

  if (wide) {
    return (
      <ScreenContainer>
        {header}
        <MetricsStrip counts={counts} metrics={metrics} showStageCounts />
        <View style={styles.toolbar}>
          <View style={styles.search}>
            <SearchField
              testID="board-search"
              value={search}
              onChangeText={setSearch}
              placeholder="Order #"
              accessibilityLabel="Search by order number"
            />
          </View>
          <View style={styles.chips}>
            <FilterChips value={filter} onChange={setFilter} />
          </View>
        </View>
        <View style={styles.columns}>
          {BOARD_COLUMNS.map(column => (
            <View key={column.status} style={styles.column}>
              <View style={styles.columnHead}>
                <View style={[styles.columnBar, { backgroundColor: theme.status[column.status] }]} />
                <Text accessibilityRole="header" style={styles.columnTitle}>
                  {column.title}
                </Text>
                <Text style={styles.columnCount}>{visibleIn(column.status).length}</Text>
              </View>
              {listFor(column.status)}
            </View>
          ))}
        </View>
      </ScreenContainer>
    );
  }

  return (
    <ScreenContainer>
      {header}
      <View style={styles.tabs}>
        <StageTabs value={stage} onChange={setStage} counts={counts} late={late} arrived={arrived} />
      </View>
      <View style={styles.phoneTools}>
        {searchOpen ? (
          <View style={styles.searchCompact}>
            <SearchField
              testID="board-search"
              value={search}
              onChangeText={setSearch}
              placeholder="Order #"
              accessibilityLabel="Search by order number"
            />
          </View>
        ) : (
          <View style={styles.chips}>
            <FilterChips value={filter} onChange={setFilter} />
          </View>
        )}
        <IconButton
          icon={searchOpen ? 'close-circle' : 'search'}
          accessibilityLabel={searchOpen ? 'Close search' : 'Search by order number'}
          active={searchOpen || search !== ''}
          onPress={() => {
            if (searchOpen) {
              setSearch('');
            }
            setSearchOpen(!searchOpen);
          }}
        />
      </View>
      <View style={styles.summary}>
        <Text style={[styles.summaryText, metrics.overdue > 0 && styles.summaryAlert]}>
          {metrics.overdue} overdue
        </Text>
        <Text style={styles.summaryText}>
          Median wait {metrics.medianWait === null ? '—' : formatWait(metrics.medianWait)}
        </Text>
      </View>
      <View style={styles.list}>{listFor(stage, twoUp ? 2 : 1)}</View>
    </ScreenContainer>
  );
};

export default BoardScreen;
