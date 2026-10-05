import React, { useEffect, useState } from 'react';
import { ActivityIndicator, FlatList, Pressable, RefreshControl, Text, View } from 'react-native';
import { useTheme, useThemedStyles } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { ScreenContainer } from '@components/ScreenContainer';
import { ScreenHeader } from '@components/ScreenHeader';
import { Icon } from '@components/Icon';
import { SearchField } from '@components/SearchField';
import { Skeleton } from '@components/Skeleton';
import { StateView } from '@components/StateView';
import { OrderMeta } from '@components/orders/OrderMeta';
import { useRealtimeStatus } from '@components/realtime/RealtimeProvider';
import { useBoardScope, useSession } from '@hooks/useAppStore';
import { useNow } from '@hooks/useNow';
import { useOrderHistory } from '@hooks/useOrderHistory';
import { useRestaurant } from '@hooks/useRestaurant';
import useNavigationHook from '@navigation/hooks/useNavigation';
import { itemCount, orderCode } from '@utils/board';
import { completedLabel, searchTerm } from '@utils/history';
import { pollIntervalFor } from '@utils/realtime';
import { createStyles } from './styles';

// Debounced so a code typed one character at a time is one request.
const SEARCH_DEBOUNCE_MS = 300;

// Orders that already went out — "did #3F2A go out?", "what was in it?".
// Strictly read-only: DELIVERED is the end of the flow.
const OrderHistoryScreen = () => {
  const styles = useThemedStyles(createStyles);
  const { colors } = useTheme();
  const navigation = useNavigationHook();
  const session = useSession();
  const scope = useBoardScope();
  const realtime = useRealtimeStatus();
  const restaurant = useRestaurant(scope.restaurantId);
  const now = useNow(60000);

  const [input, setInput] = useState('');
  const [search, setSearch] = useState<string | null>(null);
  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchTerm(input)), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [input]);

  const history = useOrderHistory(
    session?.token ?? null,
    scope,
    search,
    pollIntervalFor(realtime),
  );
  // Only while the board spans several branches; a pinned cook's history is
  // one branch, and saying so on every row would be noise.
  const showBranch = scope.locationId === null && (restaurant?.locations.length ?? 0) > 1;

  const open = (order: KitchenOrder) =>
    navigation.navigate('OrderDetailScreen', { orderId: order.id, order });

  const empty = () => {
    if (history.loading) {
      return (
        <View style={[styles.skeletons, styles.constrained]}>
          <Skeleton height={76} />
          <Skeleton height={76} />
          <Skeleton height={76} />
        </View>
      );
    }
    if (history.error) {
      return (
        <StateView
          icon="cloud-offline-outline"
          tone="danger"
          title="Couldn’t load completed orders"
          body={history.error}
          actionLabel="Try again"
          onAction={() => { history.retry(); }}
        />
      );
    }
    return search ? (
      <StateView
        testID="history-empty-search"
        icon="search"
        title="No completed order matches"
        body="Check the number on the receipt — the first eight characters are enough."
      />
    ) : (
      <StateView
        testID="history-empty-today"
        icon="receipt-outline"
        title="Nothing completed yet today"
        body="Orders appear here once they are marked Delivered or Collected."
      />
    );
  };

  return (
    <ScreenContainer>
      <ScreenHeader
        title="Completed orders"
        subtitle={search ? `All dates · matching “${search}”` : 'Today'}
        onBack={navigation.goBack}
      />
      <View style={[styles.searchRow, styles.constrained]}>
        <SearchField
          testID="history-search"
          value={input}
          onChangeText={setInput}
          placeholder="Search order # (all dates)"
          accessibilityLabel="Search completed orders by order number"
          busy={history.refreshing}
        />
      </View>
      <FlatList
        data={history.rows}
        keyExtractor={order => order.id}
        contentContainerStyle={styles.content}
        ItemSeparatorComponent={Separator}
        renderItem={({ item }) => (
          <Pressable
            testID={`history-row-${item.id}`}
            onPress={() => open(item)}
            accessibilityRole="button"
            accessibilityLabel={`${orderCode(item)}, completed ${completedLabel(item.completed_at, now)}, ${itemCount(item.items)}`}
            style={({ pressed }) => [styles.row, styles.constrained, pressed && { opacity: 0.7 }]}>
            <View style={styles.rowMain}>
              <View style={styles.rowTop}>
                <Text style={styles.code}>{orderCode(item)}</Text>
                <Text style={styles.time}>{completedLabel(item.completed_at, now)}</Text>
              </View>
              <OrderMeta
                order={item}
                branchName={showBranch ? item.restaurant_location?.branch_name : null}
              />
            </View>
            <Text style={styles.count}>{itemCount(item.items)}</Text>
            <Icon name="chevron-forward" size={20} color={colors.textMuted} />
          </Pressable>
        )}
        ListEmptyComponent={empty}
        ListFooterComponent={
          history.rows.length > 0 ? (
            <View style={styles.footer}>
              {history.loadingMore ? (
                <ActivityIndicator color={colors.textMuted} />
              ) : (
                <Text style={styles.footerText}>
                  Showing {history.rows.length} of {history.total}
                </Text>
              )}
            </View>
          ) : null
        }
        onEndReached={() => { history.loadMore(); }}
        onEndReachedThreshold={0.4}
        refreshControl={
          <RefreshControl
            refreshing={history.refreshing}
            onRefresh={() => { history.refresh(); }}
            tintColor={colors.textMuted}
          />
        }
        keyboardShouldPersistTaps="handled"
      />
    </ScreenContainer>
  );
};

const Separator = () => <View style={separatorStyle} />;

const separatorStyle = { height: 10 };

export default OrderHistoryScreen;
