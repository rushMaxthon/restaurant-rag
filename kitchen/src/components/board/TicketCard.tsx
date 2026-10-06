import React, { memo, useEffect, useRef } from 'react';
import { Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import { radius, space, useTheme } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { Icon } from '@components/Icon';
import { AdvanceButton } from '@components/orders/AdvanceButton';
import { InstructionsCallout } from '@components/orders/InstructionsCallout';
import { OrderItemsList } from '@components/orders/OrderItemsList';
import { OrderMeta } from '@components/orders/OrderMeta';
import {
  clockTime,
  formatWait,
  minutesUntilDue,
  orderCode,
  payKind,
  payLabel,
  stageLabel,
  urgencyOf,
  waitingMinutes,
} from '@utils/board';

interface TicketCardProps {
  order: KitchenOrder;
  now: Date;
  // Arrived since the last load: highlighted once, fading out.
  fresh: boolean;
  pending: boolean;
  error: string | null;
  branchName?: string | null;
  onAdvance: (order: KitchenOrder) => void;
  onOpen: (order: KitchenOrder) => void;
}

// How long the arrival highlight takes to fade.
const FRESH_FADE_MS = 4000;

// One order as a kitchen reads it: CODE → WAIT → DISHES → ACTION, top to
// bottom. The bar down the left is the order's stage; the border warms from
// grey to amber to red as it waits, and a late order says so in words too —
// colour alone is not enough on a screen read across a kitchen. Tap anywhere
// but the button for the full order.
//
// Deliberately absent: prices, address, phone, a veg mark (the API carries
// no is_veg) and a table number (fulfillment is delivery or pickup only).
const TicketCardComponent = ({
  order,
  now,
  fresh,
  pending,
  error,
  branchName,
  onAdvance,
  onOpen,
}: TicketCardProps) => {
  const theme = useTheme();
  const { colors } = theme;
  const urgency = urgencyOf(order, now);
  const stageColor = theme.status[order.status];
  const code = orderCode(order);
  const late = urgency === 'late';
  const border = late ? colors.danger : urgency === 'due' ? colors.warning : colors.border;
  // A booked order not yet due has not started waiting; "now" would read as
  // "make this immediately". It says when it is due instead.
  const dueIn = minutesUntilDue(order, now);
  const waitText = dueIn > 0 ? `in ${formatWait(dueIn)}` : formatWait(waitingMinutes(order, now));
  const waitColor = late ? colors.danger : dueIn > 0 || urgency === 'due' ? colors.warning : colors.text;
  const kind = payKind(order.payment_status);
  const payColor = kind === 'PAID' ? colors.accent : kind === 'COD' ? colors.warning : colors.danger;

  // One native-driven fade per arrival — not a loop — so a burst of new
  // orders costs a handful of animations that finish on their own.
  const highlight = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!fresh) {
      return;
    }
    highlight.setValue(1);
    const fade = Animated.timing(highlight, { toValue: 0, duration: FRESH_FADE_MS, useNativeDriver: true });
    fade.start();
    return () => fade.stop();
  }, [fresh, highlight]);

  return (
    <View
      testID={`ticket-${order.id}`}
      style={[styles.card, { backgroundColor: colors.surface, borderColor: border }, urgency !== 'calm' && styles.cardAlert]}>
      <View style={[styles.stageBar, { backgroundColor: stageColor }]} />
      <Animated.View pointerEvents="none" style={[styles.fresh, { borderColor: colors.accent, opacity: highlight }]} />

      <Pressable
        onPress={() => onOpen(order)}
        accessibilityRole="button"
        accessibilityLabel={`Order ${code}, ${dueIn > 0 ? 'due' : 'waiting'} ${waitText}. Open details.`}
        style={({ pressed }) => [styles.body, pressed && styles.pressed]}>
        <View style={styles.head}>
          <View style={styles.codeBlock}>
            {/* The code is what gets read down the phone; it shrinks to fit a
                narrow column rather than ever being cut to "#C41D8…". */}
            <Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.7} style={[styles.code, { color: colors.text }]}>
              {code}
            </Text>
            <Text style={[styles.placed, { color: colors.textMuted }]}>Placed at {clockTime(order.placed_at)}</Text>
          </View>
          <View style={styles.wait}>
            <Text style={[styles.waitValue, { color: waitColor }]}>{waitText}</Text>
            <Text style={[styles.waitCaption, { color: late ? colors.danger : colors.textMuted }]}>
              {late ? 'Overdue' : stageLabel(order.status, order.fulfillment_type)}
            </Text>
          </View>
        </View>

        {urgency !== 'calm' ? (
          <View style={styles.badges}>
            <View style={[styles.badge, { backgroundColor: colors.warningSoft }]}>
              <Icon name="warning" size={13} color={colors.warning} />
              <Text style={[styles.badgeText, { color: colors.warning }]}>Priority</Text>
            </View>
            {late ? (
              <View style={[styles.badge, { backgroundColor: colors.dangerSoft }]}>
                <Icon name="time-outline" size={13} color={colors.danger} />
                <Text style={[styles.badgeText, { color: colors.danger }]}>Needs attention</Text>
              </View>
            ) : null}
          </View>
        ) : null}

        <View style={[styles.divider, { backgroundColor: colors.border }]} />
        <OrderMeta order={order} branchName={branchName} />
        <OrderItemsList items={order.items} />
        {order.special_instructions ? <InstructionsCallout text={order.special_instructions} /> : null}
      </Pressable>

      <View style={[styles.foot, { borderTopColor: colors.border }]}>
        <View style={styles.pay}>
          <Icon name={kind === 'PAID' ? 'checkmark' : kind === 'COD' ? 'cash-outline' : 'alert-circle'} size={16} color={payColor} />
          <Text style={[styles.payText, { color: payColor }]}>{payLabel(order.payment_status)}</Text>
        </View>
        <View style={styles.action}>
          <AdvanceButton testID={`advance-${order.id}`} order={order} pending={pending} onPress={() => onAdvance(order)} />
        </View>
      </View>

      {/* The server's own sentence, unparaphrased. */}
      {error ? (
        <View style={[styles.error, { backgroundColor: colors.dangerSoft }]} accessibilityRole="alert">
          <Icon name="alert-circle" size={16} color={colors.danger} />
          <Text style={[styles.errorText, { color: colors.danger }]}>{error}</Text>
        </View>
      ) : null}
    </View>
  );
};

// Re-render only when something the card SHOWS changes. The board's clock
// ticks every 15 seconds; without this every card on every column redrew on
// each tick, though the wait only changes once a minute.
const sameMinute = (a: TicketCardProps, b: TicketCardProps) =>
  waitingMinutes(a.order, a.now) === waitingMinutes(b.order, b.now) &&
  minutesUntilDue(a.order, a.now) === minutesUntilDue(b.order, b.now);

export const TicketCard = memo(
  TicketCardComponent,
  (prev, next) =>
    prev.order === next.order &&
    prev.fresh === next.fresh &&
    prev.pending === next.pending &&
    prev.error === next.error &&
    prev.branchName === next.branchName &&
    prev.onAdvance === next.onAdvance &&
    prev.onOpen === next.onOpen &&
    sameMinute(prev, next),
);

const styles = StyleSheet.create({
  card: { borderRadius: radius.xl, borderWidth: 1, overflow: 'hidden' },
  cardAlert: { borderWidth: 1.5 },
  stageBar: { position: 'absolute', top: 0, bottom: 0, left: 0, width: 5 },
  fresh: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, borderWidth: 4, borderRadius: radius.xl },
  pressed: { opacity: 0.75 },
  body: { paddingLeft: space.lg + 5, paddingRight: space.lg, paddingTop: space.lg, gap: 12 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: space.sm },
  codeBlock: { flex: 1, gap: 2, minWidth: 0 },
  code: { fontSize: 21, fontWeight: '900', letterSpacing: 0.3, fontVariant: ['tabular-nums'] },
  placed: { fontSize: 12, fontWeight: '500' },
  wait: { alignItems: 'flex-end' },
  waitValue: { fontSize: 22, fontWeight: '900', fontVariant: ['tabular-nums'] },
  waitCaption: { fontSize: 12, fontWeight: '700' },
  badges: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 4, borderRadius: radius.pill, paddingHorizontal: 9, paddingVertical: 4 },
  badgeText: { fontSize: 12, fontWeight: '800' },
  divider: { height: StyleSheet.hairlineWidth },
  foot: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 10,
    marginTop: space.md,
    marginLeft: space.lg + 5,
    marginRight: space.lg,
    paddingTop: space.md,
    paddingBottom: space.lg,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  pay: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  payText: { fontSize: 14, fontWeight: '800' },
  // The button keeps its whole label: in a narrow tablet column it wraps
  // under the payment line rather than squeezing.
  action: { flexGrow: 1, flexBasis: 170, alignItems: 'flex-end' },
  error: { flexDirection: 'row', alignItems: 'flex-start', gap: 8, paddingHorizontal: space.lg, paddingVertical: 10 },
  errorText: { flex: 1, fontSize: 14, fontWeight: '700', lineHeight: 19 },
});
