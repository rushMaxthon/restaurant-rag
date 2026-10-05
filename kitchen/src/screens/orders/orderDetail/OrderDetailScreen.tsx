import React, { useCallback } from 'react';
import { ScrollView, Text, View, useWindowDimensions } from 'react-native';
import { useTheme, useThemedStyles } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { inkOn } from '@/themePalette';
import { ScreenContainer } from '@components/ScreenContainer';
import { ScreenHeader } from '@components/ScreenHeader';
import { Icon } from '@components/Icon';
import { Pill } from '@components/Pill';
import { Skeleton } from '@components/Skeleton';
import { StateView } from '@components/StateView';
import { AdvanceButton } from '@components/orders/AdvanceButton';
import { FactList, type Fact } from '@components/orders/FactList';
import { InstructionsCallout } from '@components/orders/InstructionsCallout';
import { OrderItemsList } from '@components/orders/OrderItemsList';
import { PaymentPill } from '@components/orders/PaymentPill';
import { StageProgress } from '@components/orders/StageProgress';
import { useRealtimeStatus } from '@components/realtime/RealtimeProvider';
import { useAdvanceOrder } from '@hooks/useAdvanceOrder';
import { useBoardScope, useSession } from '@hooks/useAppStore';
import { useNow } from '@hooks/useNow';
import { useOrder } from '@hooks/useOrder';
import { useRestaurant } from '@hooks/useRestaurant';
import useNavigationHook, { useRouteHook } from '@navigation/hooks/useNavigation';
import {
  clockTime,
  customerName,
  formatWait,
  isLiveStatus,
  isScheduled,
  itemCount,
  nextStatus,
  orderCode,
  payLabel,
  stageLabel,
  urgencyOf,
  waitingMinutes,
} from '@utils/board';
import { completedLabel, settledPaymentLabel } from '@utils/history';
import { pollIntervalFor } from '@utils/realtime';
import { TWO_PANE_MIN_WIDTH, createStyles } from './styles';

const OrderDetailScreen = () => {
  const styles = useThemedStyles(createStyles);
  const theme = useTheme();
  const { colors } = theme;
  const navigation = useNavigationHook();
  const { params } = useRouteHook<'OrderDetailScreen'>();
  const session = useSession();
  const token = session?.token ?? null;
  const scope = useBoardScope();
  const realtime = useRealtimeStatus();
  const restaurant = useRestaurant(scope.restaurantId);
  const now = useNow();
  const { width } = useWindowDimensions();
  const twoPane = width >= TWO_PANE_MIN_WIDTH;

  const { order, loading, missing, error, reload } = useOrder(
    token,
    params.orderId,
    params.order,
    pollIntervalFor(realtime),
  );
  const { advance, pending, errors } = useAdvanceOrder(token, scope);

  const onAdvance = useCallback(
    async (current: KitchenOrder) => {
      const finishing = nextStatus(current.status) === 'DELIVERED';
      const updated = await advance(current);
      // The last step ends the order's life on the board; there is nothing
      // left to do here, so go back to the work.
      if (updated && finishing) {
        navigation.goBack();
      }
    },
    [advance, navigation],
  );

  const title = order ? orderCode(order) : 'Order';

  if (!order) {
    return (
      <ScreenContainer>
        <ScreenHeader title={title} onBack={navigation.goBack} />
        {loading ? (
          <View style={styles.scroll}>
            <Skeleton height={140} />
            <Skeleton height={260} />
          </View>
        ) : missing ? (
          <StateView
            icon="file-tray-outline"
            title="This order isn’t on your board"
            body="It may belong to another branch, or it no longer exists."
            actionLabel="Back to the board"
            onAction={navigation.goBack}
          />
        ) : (
          <StateView
            icon="cloud-offline-outline"
            tone="danger"
            title="Couldn’t load this order"
            body={error ?? undefined}
            actionLabel="Try again"
            onAction={() => { reload(); }}
          />
        )}
      </ScreenContainer>
    );
  }

  const live = isLiveStatus(order.status);
  const finished = order.status === 'DELIVERED';
  const urgency = urgencyOf(order, now);
  const waitColor =
    urgency === 'late' ? colors.danger : urgency === 'due' ? colors.warning : colors.text;
  const stageColor = theme.status[order.status];
  const showBranch = scope.locationId === null && (restaurant?.locations.length ?? 0) > 1;

  const isDelivery = order.fulfillment_type === 'DELIVERY';
  const facts: Fact[] = [
    { label: 'Ordered', icon: 'time-outline', value: completedLabel(order.placed_at, now) },
    ...(isScheduled(order)
      ? [
          {
            label: 'Scheduled for',
            icon: 'calendar-outline' as const,
            value: clockTime(order.scheduled_at),
            emphasis: true,
          },
        ]
      : []),
    ...(finished
      ? [{ label: 'Completed', icon: 'checkmark-done' as const, value: completedLabel(order.completed_at, now) }]
      : []),
    {
      label: 'Type',
      icon: isDelivery ? 'bicycle' : 'bag-handle-outline',
      value: isDelivery ? 'Delivery' : 'Pickup',
    },
    ...(customerName(order)
      ? [{ label: 'Customer', icon: 'person-outline' as const, value: customerName(order)! }]
      : []),
    ...(showBranch && order.restaurant_location
      ? [{ label: 'Branch', icon: 'location-outline' as const, value: order.restaurant_location.branch_name }]
      : []),
    {
      label: 'Payment',
      icon: 'cash-outline',
      value: (
        <PaymentPill
          status={order.payment_status}
          label={
            finished ? settledPaymentLabel(order.payment_status) : payLabel(order.payment_status)
          }
        />
      ),
    },
  ];

  const waitTint =
    urgency === 'late' ? colors.dangerSoft : urgency === 'due' ? colors.warningSoft : colors.surfaceMuted;
  const hero = (
    <View style={styles.card}>
      <View style={[styles.accent, { backgroundColor: stageColor }]} />
      <View style={styles.hero}>
        <View style={styles.heroText}>
          <Text style={styles.code}>{orderCode(order)}</Text>
          <Pill
            size="md"
            label={stageLabel(order.status, order.fulfillment_type)}
            color={inkOn(stageColor)}
            background={stageColor}
          />
        </View>
        {live ? (
          <View
            style={[styles.waitBox, { backgroundColor: waitTint }]}
            accessible
            accessibilityLabel={`Waiting ${formatWait(waitingMinutes(order, now))}`}>
            <Text style={[styles.waitLabel, { color: waitColor }]}>Waiting</Text>
            <Text style={[styles.waitValue, { color: waitColor }]}>
              {formatWait(waitingMinutes(order, now))}
            </Text>
          </View>
        ) : null}
      </View>
      <View style={styles.divider} />
      <StageProgress status={order.status} fulfillment={order.fulfillment_type} />
      {finished ? (
        <Banner
          icon="checkmark-circle"
          color={colors.accent}
          background={colors.accentSoft}
          text={`${order.fulfillment_type === 'DELIVERY' ? 'Delivered' : 'Collected'} · ${completedLabel(order.completed_at, now)}. Nothing left to do.`}
        />
      ) : order.status === 'CANCELLED' ? (
        <Banner
          icon="close-circle"
          color={colors.danger}
          background={colors.dangerSoft}
          text="This order was cancelled. Do not prepare it."
        />
      ) : order.status === 'PAYMENT_PENDING' ? (
        <Banner
          icon="hourglass-outline"
          color={colors.warning}
          background={colors.warningSoft}
          text="Waiting for the customer’s payment. Don’t start it yet."
        />
      ) : null}
    </View>
  );

  const factsCard = (
    <View style={styles.card}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>
        Details
      </Text>
      <FactList facts={facts} />
    </View>
  );

  const itemsCard = (
    <View style={styles.card}>
      <View style={styles.sectionHead}>
        <Text accessibilityRole="header" style={styles.sectionTitle}>
          Items
        </Text>
        <View style={styles.countPill}>
          <Text style={styles.countPillText}>{itemCount(order.items)}</Text>
        </View>
      </View>
      <OrderItemsList items={order.items} large />
      {order.special_instructions ? (
        <InstructionsCallout text={order.special_instructions} />
      ) : null}
    </View>
  );

  const actionError = errors[order.id];
  const next = nextStatus(order.status);
  const actionBar = live ? (
    <View style={styles.actionBar}>
      {actionError ? (
        <View accessibilityRole="alert" style={styles.actionError}>
          <Icon name="alert-circle" size={16} color={colors.danger} />
          <Text style={styles.actionErrorText}>{actionError}</Text>
        </View>
      ) : null}
      {next ? (
        <View style={styles.nextHint}>
          <View style={[styles.nextHintDot, { backgroundColor: theme.status[next] }]} />
          <Text style={styles.nextHintText}>
            Moves to {stageLabel(next, order.fulfillment_type)}
          </Text>
        </View>
      ) : null}
      <AdvanceButton
        testID="detail-advance"
        size="lg"
        order={order}
        pending={pending.has(order.id)}
        onPress={() => { onAdvance(order); }}
      />
    </View>
  ) : null;

  return (
    <ScreenContainer>
      {/* The code is the card's headline below; the bar only says where
          you are, so it is not printed twice. */}
      <ScreenHeader
        title={finished ? 'Completed order' : 'Order details'}
        onBack={navigation.goBack}
      />
      {twoPane ? (
        // Each ScrollView sits in a plain View that owns the flex share: a
        // ScrollView's own `flex` is not honoured as a row child, which put
        // the dishes in the narrow pane.
        <View style={styles.panes}>
          <View style={styles.paneMain}>
            <ScrollView contentContainerStyle={styles.paneScroll}>{itemsCard}</ScrollView>
          </View>
          <View style={styles.paneSide}>
            <ScrollView contentContainerStyle={styles.paneScroll}>
              {hero}
              {factsCard}
            </ScrollView>
            {actionBar ? <View style={styles.actionCard}>{actionBar}</View> : null}
          </View>
        </View>
      ) : (
        <>
          <ScrollView style={styles.flex} contentContainerStyle={styles.scroll}>
            {hero}
            {itemsCard}
            {factsCard}
          </ScrollView>
          {actionBar}
        </>
      )}
    </ScreenContainer>
  );
};

const Banner = ({
  icon,
  color,
  background,
  text,
}: {
  icon: 'checkmark-circle' | 'close-circle' | 'hourglass-outline';
  color: string;
  background: string;
  text: string;
}) => {
  const styles = useThemedStyles(createStyles);
  return (
    <View style={[styles.banner, { backgroundColor: background }]}>
      <Icon name={icon} size={22} color={color} />
      <Text style={[styles.bannerText, { color }]}>{text}</Text>
    </View>
  );
};

export default OrderDetailScreen;
