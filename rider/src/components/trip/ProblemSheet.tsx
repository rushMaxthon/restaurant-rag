import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { Sheet } from '@components/ui/Sheet';
import { SUPPORT_PHONE } from '@/config/api';
import { useI18n } from '@/i18n';
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
  const { t } = useI18n();
  const atDoor = trip.step === 'at_drop';
  // Re-check the clock while the sheet is open at the door, so the button
  // unlocks at ten minutes without the rider closing and reopening it.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!open || !atDoor) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(timer);
  }, [open, atDoor]);
  const waitedMin = trip.arrived_drop_at
    ? (now - new Date(trip.arrived_drop_at).getTime()) / 60_000
    : 0;
  const canGiveUp =
    waitedMin >= WAIT_MINUTES && trip.call_attempts >= CALLS_NEEDED;

  return (
    <Sheet open={open} onClose={onClose} title={t('trip.problemTitle')}>
      {trip.pickup.phone ? (
        <Line
          icon="restaurant"
          label={t('trip.callRestaurant')}
          hint={trip.pickup.name}
          onPress={() => void call(trip.pickup.phone)}
        />
      ) : null}
      {trip.drop.phone ? (
        <Line
          icon="home"
          label={t('trip.callCustomer')}
          hint={trip.drop.name}
          onPress={async () => {
            const ok = await call(trip.drop.phone);
            if (ok && atDoor) onCustomerCalled();
          }}
        />
      ) : null}
      <Line
        icon="headset"
        label={t('trip.callSupport')}
        hint={t('trip.supportHint')}
        onPress={() => void call(SUPPORT_PHONE)}
      />

      {atDoor ? (
        <View style={styles.giveUp}>
          <AppText variant="caption" tone="muted" align="center">
            {t('trip.notAnsweringHelp', {
              calls: CALLS_NEEDED,
              minutes: WAIT_MINUTES,
              made: trip.call_attempts,
            })}
          </AppText>
          <Button
            kind="danger"
            size="md"
            icon="person-remove"
            label={t('trip.customerUnavailable')}
            loading={unavailableBusy}
            disabledReason={
              canGiveUp
                ? null
                : t('trip.unavailableAfter', {
                    minutes: WAIT_MINUTES,
                    calls: CALLS_NEEDED,
                  })
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
