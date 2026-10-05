import React, { memo, useEffect, useRef } from 'react';
import { Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import { radius, space, useTheme, type AppTheme } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { Icon } from '@components/Icon';
import { AdvanceButton } from '@components/orders/AdvanceButton';
import { InstructionsCallout } from '@components/orders/InstructionsCallout';
import { OrderItemsList } from '@components/orders/OrderItemsList';
import { OrderMeta } from '@components/orders/OrderMeta';
import { PaymentPill } from '@components/orders/PaymentPill';
import {
  clockTime,
  formatWait,
  minutesUntilDue,
  orderCode,
  payLabel,
  urgencyOf,
  waitingMinutes,
  type Urgency,
} from '@utils/board';
import { priorityLabel } from '@utils/metrics';

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

const toneOf = (urgency: Urgency, { colors }: AppTheme) => {
  switch (urgency) {
    case 'late':
      return { band: colors.dangerSoft, border: colors.danger, ink: colors.danger };
    case 'due':
      return { band: colors.warningSoft, border: colors.warning, ink: colors.warning };
    default:
      return { band: colors.surface, border: colors.border, ink: colors.text };
  }
};

// One order as a kitchen reads it: CODE → WAIT → DISHES → ACTION, top to
// bottom. The header band carries urgency in colour, so a glance across a
// column finds the late ones before reading a single word. Tap anywhere but
// the button for the full order.
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
  const tone = toneOf(urgency, theme);
  const flag = priorityLabel(order, now);
  const code = orderCode(order);
  // A booked order not yet due has not started waiting; "now" would read as
  // "make this immediately". It says when it is due instead.
  const dueIn = minutesUntilDue(order, now);
  const waitText = dueIn > 0 ? `in ${formatWait(dueIn)}` : formatWait(waitingMinutes(order, now));

  // One native-driven fade per arrival — not a loop — so a burst of new
  // orders costs a handful of animations that finish on their own.
  const highlight = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!fresh) {
      return;
    }
    highlight.setValue(1);
    const fade = Animated.timing(highlight, {
      toValue: 0,
      duration: FRESH_FADE_MS,
      useNativeDriver: true,
    });
    fade.start();
    return () => fade.stop();
  }, [fresh, highlight]);

  return (
    <View
      testID={`ticket-${order.id}`}
      style={[
        styles.card,
        urgency === 'calm' ? styles.cardCalm : styles.cardAlert,
        { backgroundColor: colors.surface, borderColor: tone.border },
      ]}>
      <Animated.View
        pointerEvents="none"
        style={[styles.fresh, { borderColor: colors.accent, opacity: highlight }]}
      />
      <Pressable
        onPress={() => onOpen(order)}
        accessibilityRole="button"
        accessibilityLabel={`Order ${code}, ${dueIn > 0 ? 'due' : 'waiting'} ${waitText}. Open details.`}
        style={({ pressed }) => pressed && styles.pressed}>
        <View style={[styles.band, { backgroundColor: tone.band, borderBottomColor: colors.border }]}>
          <View style={styles.codeBlock}>
            {/* The code is what gets read down the phone; it shrinks to fit a
                narrow column rather than ever being cut to "#C41D8…". */}
            <Text
              numberOfLines={1}
              adjustsFontSizeToFit
              minimumFontScale={0.7}
              style={[styles.code, { color: colors.text }]}>
              {code}
            </Text>
            {flag ? (
              <View style={styles.flag}>
                <Icon name={urgency === 'late' ? 'flame' : 'hourglass-outline'} size={13} color={tone.ink} />
                <Text style={[styles.flagText, { color: tone.ink }]}>{flag}</Text>
              </View>
            ) : (
              <Text style={[styles.placedAt, { color: colors.textMuted }]}>
                Placed {clockTime(order.placed_at)}
              </Text>
            )}
          </View>
          <View style={styles.wait}>
            <Text style={[styles.waitValue, { color: dueIn > 0 ? colors.warning : tone.ink }]}>
              {waitText}
            </Text>
            {flag ? (
              <Text style={[styles.placedAt, { color: colors.textMuted }]}>{clockTime(order.placed_at)}</Text>
            ) : null}
          </View>
        </View>

        <View style={styles.body}>
          <OrderMeta order={order} branchName={branchName} />
          <OrderItemsList items={order.items} />
          {order.special_instructions ? <InstructionsCallout text={order.special_instructions} /> : null}
        </View>
      </Pressable>

      <View style={styles.foot}>
        <PaymentPill status={order.payment_status} label={payLabel(order.payment_status)} />
        <AdvanceButton
          testID={`advance-${order.id}`}
          order={order}
          pending={pending}
          onPress={() => onAdvance(order)}
        />
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
  card: { borderRadius: radius.xl, overflow: 'hidden' },
  cardCalm: { borderWidth: 1 },
  cardAlert: { borderWidth: 2 },
  fresh: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    borderWidth: 4,
    borderRadius: radius.xl,
  },
  pressed: { opacity: 0.75 },
  band: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: space.sm,
    paddingHorizontal: space.lg,
    paddingTop: 14,
    paddingBottom: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  codeBlock: { flex: 1, gap: 4, minWidth: 0 },
  code: { fontSize: 21, fontWeight: '900', letterSpacing: 0.4, fontVariant: ['tabular-nums'] },
  flag: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  flagText: { fontSize: 12, fontWeight: '900', letterSpacing: 0.6 },
  placedAt: { fontSize: 12, fontWeight: '600' },
  wait: { alignItems: 'flex-end', gap: 2 },
  waitValue: { fontSize: 24, fontWeight: '900', fontVariant: ['tabular-nums'] },
  body: { paddingHorizontal: space.lg, paddingTop: 14, gap: 14 },
  foot: { gap: 10, paddingHorizontal: space.lg, paddingTop: 14, paddingBottom: space.lg },
  error: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
    paddingHorizontal: space.lg,
    paddingVertical: 10,
  },
  errorText: { flex: 1, fontSize: 14, fontWeight: '700', lineHeight: 19 },
});
