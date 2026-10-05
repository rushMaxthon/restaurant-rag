import React, { memo, useEffect, useRef } from 'react';
import { Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import { useTheme, type AppTheme } from '@/theme';
import type { KitchenOrder } from '@/types/app';
import { Pill } from '@components/Pill';
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
  // Arrived since the last load: pulses for a few seconds, then never again.
  fresh: boolean;
  pending: boolean;
  error: string | null;
  branchName?: string | null;
  onAdvance: (order: KitchenOrder) => void;
  onOpen: (order: KitchenOrder) => void;
}

const urgencyColors = (urgency: Urgency, { colors }: AppTheme) => {
  switch (urgency) {
    case 'late':
      return { border: colors.danger, wait: colors.danger, badge: colors.dangerSoft };
    case 'due':
      return { border: colors.warning, wait: colors.warning, badge: colors.warningSoft };
    default:
      return { border: colors.border, wait: colors.text, badge: colors.surfaceMuted };
  }
};

// One order as a kitchen reads it: CODE → WAIT → DISHES → ACTION, top to
// bottom. Tap anywhere but the button for the full order.
//
// Deliberately absent: prices, address, phone, a veg mark (the API carries
// no is_veg, and a dot guessed from a dish name is how a plate gets sent
// back), and a table number (fulfillment is delivery or pickup only).
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
  const tone = urgencyColors(urgency, theme);
  const flag = priorityLabel(order, now);
  const code = orderCode(order);
  // A booked order not yet due has not started waiting; "now" would read as
  // "make this immediately". It says when it is due instead.
  const dueIn = minutesUntilDue(order, now);
  const waitText = dueIn > 0 ? `in ${formatWait(dueIn)}` : formatWait(waitingMinutes(order, now));

  const pulse = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!fresh) {
      pulse.setValue(0);
      return;
    }
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(pulse, { toValue: 1, duration: 450, useNativeDriver: true }),
        Animated.timing(pulse, { toValue: 0.25, duration: 450, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [fresh, pulse]);

  return (
    <View
      testID={`ticket-${order.id}`}
      style={[
        styles.card,
        urgency === 'calm' ? styles.cardCalm : styles.cardAlert,
        { backgroundColor: colors.surface, borderColor: tone.border },
      ]}>
      {/* The arrival highlight, on its own layer so it animates natively. */}
      <Animated.View
        pointerEvents="none"
        style={[styles.fresh, { borderColor: colors.accent, opacity: pulse }]}
      />
      <Pressable
        onPress={() => onOpen(order)}
        accessibilityRole="button"
        accessibilityLabel={`Order ${code}, ${dueIn > 0 ? 'due' : 'waiting'} ${waitText}. Open details.`}
        style={({ pressed }) => [styles.body, pressed && { opacity: 0.7 }]}>
        {/* Code with its badge UNDER it, so a narrow tablet column never
            has to clip the badge to fit the wait time beside them. */}
        <View style={styles.head}>
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
              <Pill
                label={flag}
                color={tone.wait}
                background={tone.badge}
                icon={urgency === 'late' ? 'flame' : 'hourglass-outline'}
              />
            ) : null}
          </View>
          <View style={styles.wait}>
            <Text style={[styles.waitValue, { color: dueIn > 0 ? colors.warning : tone.wait }]}>
              {waitText}
            </Text>
            <Text style={[styles.placedAt, { color: colors.textMuted }]}>
              {clockTime(order.placed_at)}
            </Text>
          </View>
        </View>

        <OrderMeta order={order} branchName={branchName} />

        <View style={[styles.divider, { backgroundColor: colors.border }]} />

        <OrderItemsList items={order.items} />

        {order.special_instructions ? (
          <InstructionsCallout text={order.special_instructions} />
        ) : null}
      </Pressable>

      {/* Payment, then the action on its own full-width row: the button
          keeps its whole label however narrow the column. */}
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
        <Text
          accessibilityRole="alert"
          style={[styles.error, { color: colors.danger, backgroundColor: colors.dangerSoft }]}>
          {error}
        </Text>
      ) : null}
    </View>
  );
};

export const TicketCard = memo(TicketCardComponent);

const styles = StyleSheet.create({
  card: { borderRadius: 18, overflow: 'hidden' },
  cardCalm: { borderWidth: 1 },
  cardAlert: { borderWidth: 2 },
  fresh: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, borderWidth: 4, borderRadius: 18 },
  body: { padding: 16, gap: 10 },
  head: { flexDirection: 'row', alignItems: 'flex-start', gap: 8 },
  codeBlock: { flex: 1, gap: 6, minWidth: 0 },
  code: { fontSize: 20, fontWeight: '900', letterSpacing: 0.5, fontVariant: ['tabular-nums'] },
  wait: { alignItems: 'flex-end' },
  waitValue: { fontSize: 22, fontWeight: '900', fontVariant: ['tabular-nums'] },
  placedAt: { fontSize: 12, fontWeight: '600' },
  divider: { height: StyleSheet.hairlineWidth, marginVertical: 2 },
  foot: { gap: 10, paddingHorizontal: 16, paddingBottom: 16 },
  error: {
    fontSize: 14,
    fontWeight: '600',
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
});
