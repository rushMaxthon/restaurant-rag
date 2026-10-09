import React from 'react';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { Sheet } from '@components/ui/Sheet';
import { SUPPORT_PHONE } from '@/config/api';
import type { Trip } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';
import { call } from '@utils/links';

/** Minutes at the door, and calls made, before a rider may give up on a customer. */
export const WAIT_MINUTES = 10;
export const CALLS_NEEDED = 2;

function Line({
  icon,
  label,
  hint,
  onPress,
}: {
  icon: IconName;
  label: string;
  hint: string;
  onPress: () => void;
}) {
  const { colors } = useTheme();
  return (
    <Card onPress={onPress} style={styles.line}>
      <View style={[styles.icon, { backgroundColor: colors.surfaceAlt }]}>
        <Icon name={icon} size={20} color={colors.text} />
      </View>
      <View style={styles.flex}>
        <AppText variant="bodyStrong">{label}</AppText>
        <AppText variant="caption" tone="muted">
          {hint}
        </AppText>
      </View>
      <Icon name="call" size={18} color={colors.primary} />
    </Card>
  );
}

/**
 * The one place for "something is wrong": every phone number the rider may
 * need, and at the door the gated way out when the customer never answers.
 * Gated hard - two calls and ten minutes - because it ends a paid trip and
 * the customer's dinner, and the server checks the same rule again.
 */
export function ProblemSheet({
  open,
  onClose,
  trip,
  onCustomerCalled,
  onUnavailable,
  unavailableBusy,
}: {
  open: boolean;
  onClose: () => void;
  trip: Trip;
  onCustomerCalled: () => void;
  onUnavailable: () => void;
  unavailableBusy: boolean;
}) {
  const atDoor = trip.step === 'at_drop';
  const waitedMin = trip.arrived_drop_at
    ? (Date.now() - new Date(trip.arrived_drop_at).getTime()) / 60_000
    : 0;
  const canGiveUp =
    waitedMin >= WAIT_MINUTES && trip.call_attempts >= CALLS_NEEDED;

  return (
    <Sheet open={open} onClose={onClose} title="Having a problem?">
      {trip.pickup.phone ? (
        <Line
          icon="restaurant"
          label="Call the restaurant"
          hint={trip.pickup.name}
          onPress={() => void call(trip.pickup.phone)}
        />
      ) : null}
      {trip.drop.phone ? (
        <Line
          icon="home"
          label="Call the customer"
          hint={trip.drop.name}
          onPress={async () => {
            const ok = await call(trip.drop.phone);
            if (ok && atDoor) onCustomerCalled();
          }}
        />
      ) : null}
      <Line
        icon="headset"
        label="Call support"
        hint="Wrong address, order not ready, anything else"
        onPress={() => void call(SUPPORT_PHONE)}
      />

      {atDoor ? (
        <View style={styles.giveUp}>
          <AppText variant="caption" tone="muted" align="center">
            Customer not answering? Call them at least {CALLS_NEEDED} times and
            wait {WAIT_MINUTES} minutes at the door. Calls made:{' '}
            {trip.call_attempts}.
          </AppText>
          <Button
            kind="danger"
            size="md"
            icon="person-remove"
            label="Customer unavailable"
            loading={unavailableBusy}
            disabledReason={
              canGiveUp
                ? null
                : `Available after ${WAIT_MINUTES} min and ${CALLS_NEEDED} calls`
            }
            onPress={onUnavailable}
          />
        </View>
      ) : null}
    </Sheet>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingVertical: space.md,
  },
  icon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  giveUp: { gap: space.sm, marginTop: space.md },
});
