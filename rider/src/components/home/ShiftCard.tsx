import React, { useEffect } from 'react';
import { useI18n } from '@/i18n';
import { StyleSheet, View } from 'react-native';
import Animated, {
  Easing,
  FadeIn,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { OnlineToggle } from '@components/ui/OnlineToggle';
import { GuideTarget } from '@/guide/GuideProvider';
import { TARGETS } from '@/guide/tours';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';

type Props = {
  online: boolean;
  onChange: (next: boolean) => void;
  busy: boolean;
  disabledReason: string | null;
  error: string | null;
  /** Always the strip, offline too: the Orders tab, where the board is the point. */
  strip?: boolean;
  /**
   * Whether this is the control the Home tip points at. Tabs stay mounted, so
   * a second copy registered under the same target would take the tip over.
   */
  guide?: boolean;
  /** The strip's second line while offline. */
  offlineHint?: string;
};

/**
 * Home's shift control, sized to what the rider needs from it.
 *
 * Online, it is a strip: a pulsing dot says "you're getting orders" and the
 * rest of the screen goes to the orders themselves - a rider between
 * deliveries is looking for work, not at an animation. Offline it is the
 * screen's one big action, because going online is the only thing to do.
 */
export function ShiftCard(props: Props) {
  return props.online || props.strip ? (
    <ShiftStrip {...props} />
  ) : (
    <OfflineCard {...props} />
  );
}

function ShiftStrip({
  online,
  onChange,
  busy,
  disabledReason,
  error,
  guide = true,
  offlineHint,
}: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const toggle = (
    <OnlineToggle
      compact
      online={online}
      onChange={onChange}
      busy={busy}
      disabledReason={disabledReason}
      // The reason is in the strip's own line; the compact toggle has no
      // room for a second copy beneath it.
      showReason={false}
    />
  );
  return (
    <Animated.View entering={FadeIn.duration(300)}>
      <Card
        style={[
          styles.strip,
          { borderColor: online ? colors.success : colors.border },
        ]}
      >
        <View style={styles.stripRow}>
          {online ? (
            <Beacon color={colors.success} />
          ) : (
            <View style={styles.beacon}>
              <Icon name="moon" size={18} color={colors.textMuted} />
            </View>
          )}
          <AppText variant="bodyStrong" style={styles.flex} numberOfLines={2}>
            {online ? t('home.online') : t('home.offline')}
          </AppText>
          {guide ? (
            <GuideTarget id={TARGETS.homeToggle}>{toggle}</GuideTarget>
          ) : (
            toggle
          )}
        </View>
        {/* Under the row, full width: beside a 148 dp toggle at a large font
            it had ~96 dp and was cut off. */}
        <AppText variant="caption" tone="muted" style={styles.hint}>
          {online
            ? disabledReason ?? t('home.lookingForOrders')
            : offlineHint ?? t('home.offlineHint')}
        </AppText>
        {error ? (
          <AppText variant="caption" tone="danger">
            {error}
          </AppText>
        ) : null}
      </Card>
    </Animated.View>
  );
}

function OfflineCard({ online, onChange, busy, disabledReason, error }: Props) {
  const { colors } = useTheme();
  const { t } = useI18n();
  return (
    <Animated.View entering={FadeIn.duration(300)}>
      <Card style={styles.offline}>
        <View style={styles.offlineHead}>
          <View
            style={[styles.offIcon, { backgroundColor: colors.surfaceAlt }]}
          >
            <Icon name="moon-outline" size={22} color={colors.textMuted} />
          </View>
          <View style={styles.flex}>
            <AppText variant="heading">{t('home.offline')}</AppText>
            <AppText variant="caption" tone="muted">
              {t('home.offlineBody')}
            </AppText>
          </View>
        </View>
        <GuideTarget id={TARGETS.homeToggle} style={styles.center}>
          <OnlineToggle
            online={online}
            onChange={onChange}
            busy={busy}
            disabledReason={disabledReason}
          />
        </GuideTarget>
        {error ? (
          <AppText variant="caption" tone="danger" align="center">
            {error}
          </AppText>
        ) : null}
      </Card>
    </Animated.View>
  );
}

/** A dot with one ring rippling out of it: "live", in 28 dp. */
function Beacon({ color }: { color: string }) {
  const { t: tr } = useI18n();
  const t = useSharedValue(0);
  useEffect(() => {
    t.value = withRepeat(
      withTiming(1, { duration: 1800, easing: Easing.out(Easing.quad) }),
      -1,
      false,
    );
  }, [t]);
  const ring = useAnimatedStyle(() => ({
    opacity: 0.55 * (1 - t.value),
    transform: [{ scale: 0.6 + t.value * 1.2 }],
  }));
  return (
    <View style={styles.beacon} accessibilityLabel={tr('home.searching')}>
      <Animated.View
        style={[styles.beaconRing, { borderColor: color }, ring]}
      />
      <View style={[styles.beaconDot, { backgroundColor: color }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { alignSelf: 'center' },
  strip: {
    gap: space.sm,
    paddingVertical: space.md,
    borderRadius: radius.xl,
    borderWidth: 1,
  },
  stripRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  // Lines up with the title, past the 28 dp beacon and the row gap.
  hint: { marginLeft: 28 + space.md, marginTop: -space.sm },
  offline: {
    gap: space.lg,
    paddingVertical: space.xl,
    borderRadius: radius.xxl,
  },
  offlineHead: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  offIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: 'center',
    justifyContent: 'center',
  },
  beacon: {
    width: 28,
    height: 28,
    alignItems: 'center',
    justifyContent: 'center',
  },
  beaconRing: {
    position: 'absolute',
    width: 28,
    height: 28,
    borderRadius: 14,
    borderWidth: 2,
  },
  beaconDot: { width: 12, height: 12, borderRadius: 6 },
});
