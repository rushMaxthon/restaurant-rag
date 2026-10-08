import React from 'react';
import { StyleSheet, View } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { useRider } from '@/store/RiderProvider';
import { useTheme } from '@theme/ThemeProvider';
import { motion, space } from '@theme/tokens';
import { rupees } from '@utils/format';

/**
 * Home's pointer to the Orders board: how many are waiting and the best pay
 * among them. The list itself lives on the Orders tab, so Home stays about
 * going online.
 */
export function OpenOrders() {
  const { colors } = useTheme();
  const nav = useNavigation<{ navigate: (route: 'Orders') => void }>();
  const { me, trip, openOrders } = useRider();
  if (me?.status !== 'ONLINE' || trip || openOrders.length === 0) return null;
  const best = Math.max(...openOrders.map(o => Number(o.earning_estimate)));
  const missed = openOrders.some(o => o.missed);

  return (
    <Animated.View entering={FadeInDown.duration(motion.base)}>
      <Card
        onPress={() => nav.navigate('Orders')}
        style={[styles.card, { borderColor: colors.primary }]}
      >
        <View style={[styles.badge, { backgroundColor: colors.primarySoft }]}>
          <Icon name="flash" size={18} color={colors.primary} />
        </View>
        <View style={styles.flex}>
          <AppText variant="bodyStrong">
            {openOrders.length} open order{openOrders.length === 1 ? '' : 's'}{' '}
            near you
          </AppText>
          <AppText variant="caption" tone="muted">
            {missed ? 'Including one you missed · ' : ''}up to {rupees(best)}
          </AppText>
        </View>
        <AppText variant="label" tone="primary">
          View
        </AppText>
        <Icon name="chevron-forward" size={18} color={colors.primary} />
      </Card>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderWidth: 1,
  },
  badge: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  flex: { flex: 1 },
});
