import React, { useCallback, useEffect, useRef, useState } from 'react';
import { FlatList, StyleSheet, View, useWindowDimensions } from 'react-native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import Animated, { FadeIn, FadeInDown } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AnimatedAmount } from '@components/ui/AnimatedAmount';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { CountdownRing } from '@components/ui/CountdownRing';
import { OnlineToggle } from '@components/ui/OnlineToggle';
import { SlideToConfirm } from '@components/ui/SlideToConfirm';
import { useGuide } from '@/guide/GuideProvider';
import { useI18n, type Key } from '@/i18n';
import { usePermissions } from '@hooks/usePermissions';
import type { RootStackParamList } from '@navigation/types';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { haptic } from '@utils/haptics';

/**
 * How the app works, in four cards a new rider can touch. Each card shows
 * the real control, not a drawing of it: the toggle toggles, the slide
 * slides, so the first real order is the second time they have done it.
 */

type Card = {
  key: string;
  titleKey: Key;
  bodyKey: Key;
  demo: React.ComponentType;
};

function OnlineDemo() {
  const [online, setOnline] = useState(false);
  return <OnlineToggle online={online} onChange={setOnline} />;
}

function RingDemo() {
  const [round, setRound] = useState(0);
  const [expiresAt, setExpiresAt] = useState(() => Date.now() + 30_000);
  useEffect(() => setExpiresAt(Date.now() + 30_000), [round]);
  return (
    <CountdownRing
      key={round}
      expiresAt={expiresAt}
      totalMs={30_000}
      size={140}
      onExpire={() => setRound(r => r + 1)}
    />
  );
}

function SlideDemo() {
  const { t } = useI18n();
  const [done, setDone] = useState(0);
  const [resetKey, setResetKey] = useState(0);
  useEffect(() => {
    if (!done) return;
    const timer = setTimeout(() => setResetKey(k => k + 1), 1400);
    return () => clearTimeout(timer);
  }, [done]);
  return (
    <View style={styles.slideWrap}>
      <SlideToConfirm
        label={t('account.intro.slideLabel')}
        icon="restaurant"
        resetKey={resetKey}
        onConfirm={() => {
          haptic('success');
          setDone(d => d + 1);
        }}
      />
      <AppText
        variant="caption"
        tone={done ? 'success' : 'muted'}
        align="center"
      >
        {done ? t('account.intro.slideDone') : t('account.intro.slideTry')}
      </AppText>
    </View>
  );
}

const CODE = ['4', '7', '1', '9'];

function CodeDemo() {
  const { colors } = useTheme();
  const { t } = useI18n();
  const [filled, setFilled] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setFilled(f => (f >= 5 ? 0 : f + 1)), 650);
    return () => clearInterval(timer);
  }, []);
  const paid = filled >= 4;
  return (
    <View style={styles.codeWrap}>
      <View style={styles.boxes}>
        {CODE.map((d, i) => (
          <View
            key={i}
            style={[
              styles.box,
              {
                borderColor: i < filled ? colors.primary : colors.border,
                backgroundColor: colors.surface,
              },
            ]}
          >
            <AppText variant="title">{i < filled ? d : ''}</AppText>
          </View>
        ))}
      </View>
      <View style={[styles.paid, paid ? null : styles.hidden]}>
        <AppText variant="micro" tone="success">
          {t('account.intro.youEarned')}
        </AppText>
        {paid ? (
          <AnimatedAmount value={52} tone="success" duration={500} />
        ) : null}
      </View>
    </View>
  );
}

const CARDS: Card[] = [
  {
    key: 'online',
    titleKey: 'account.intro.onlineTitle',
    bodyKey: 'account.intro.onlineBody',
    demo: OnlineDemo,
  },
  {
    key: 'ring',
    titleKey: 'account.intro.ringTitle',
    bodyKey: 'account.intro.ringBody',
    demo: RingDemo,
  },
  {
    key: 'slide',
    titleKey: 'account.intro.slideTitle',
    bodyKey: 'account.intro.slideBody',
    demo: SlideDemo,
  },
  {
    key: 'code',
    titleKey: 'account.intro.codeTitle',
    bodyKey: 'account.intro.codeBody',
    demo: CodeDemo,
  },
];

export function IntroScreen({
  navigation,
  route,
}: NativeStackScreenProps<RootStackParamList, 'Intro'>) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const { markIntroSeen } = useGuide();
  const { ready, state: permissionState } = usePermissions();
  const list = useRef<FlatList<Card>>(null);
  const [index, setIndex] = useState(0);
  // A horizontal list gives its rows no height of their own: measured, so a card can centre itself.
  const [listHeight, setListHeight] = useState(0);
  const replay = route.params?.replay === true;
  const last = index === CARDS.length - 1;

  const leave = useCallback(() => {
    markIntroSeen();
    if (replay) {
      navigation.goBack();
      return;
    }
    // Permissions sits ON TOP of Main, never alone: going online is what the
    // permissions gate, and Home says so, so a rider may always get past it.
    if (ready || permissionState === null)
      navigation.reset({ index: 0, routes: [{ name: 'Main' }] });
    else
      navigation.reset({
        index: 1,
        routes: [{ name: 'Main' }, { name: 'Permissions' }],
      });
  }, [markIntroSeen, replay, ready, permissionState, navigation]);

  const goTo = (i: number) => {
    list.current?.scrollToIndex({ index: i, animated: true });
    setIndex(i);
  };

  return (
    <View
      style={[
        styles.root,
        { backgroundColor: colors.bg, paddingTop: insets.top + space.md },
      ]}
    >
      <View style={styles.top}>
        <AppText variant="micro" tone="muted">
          {t('account.intro.howItWorks')}
        </AppText>
        <Button
          kind="ghost"
          size="md"
          label={replay ? t('common.close') : t('common.skip')}
          onPress={leave}
        />
      </View>

      <View
        style={styles.list}
        onLayout={e => setListHeight(e.nativeEvent.layout.height)}
      >
        <FlatList
          ref={list}
          data={CARDS}
          keyExtractor={c => c.key}
          horizontal
          pagingEnabled
          showsHorizontalScrollIndicator={false}
          onMomentumScrollEnd={e =>
            setIndex(Math.round(e.nativeEvent.contentOffset.x / width))
          }
          getItemLayout={(_, i) => ({
            length: width,
            offset: width * i,
            index: i,
          })}
          renderItem={({ item, index: i }) => {
            const Demo = item.demo;
            return (
              <View
                style={[
                  styles.card,
                  { width, height: listHeight || undefined },
                ]}
              >
                <View
                  style={[styles.stage, { backgroundColor: colors.surfaceAlt }]}
                >
                  {/* Only the card on screen runs its demo: four loops at once cost a cheap phone. */}
                  {i === index ? (
                    <Animated.View
                      entering={FadeIn.duration(300)}
                      style={styles.demo}
                    >
                      <Demo />
                    </Animated.View>
                  ) : null}
                </View>
                <Animated.View
                  key={`${item.key}-${i === index}`}
                  entering={FadeInDown.duration(300)}
                >
                  <AppText variant="title" align="center">
                    {t(item.titleKey)}
                  </AppText>
                  <AppText tone="muted" align="center" style={styles.body}>
                    {t(item.bodyKey)}
                  </AppText>
                </Animated.View>
              </View>
            );
          }}
        />
      </View>

      <View
        style={[styles.footer, { paddingBottom: insets.bottom + space.lg }]}
      >
        <View
          style={styles.dots}
          accessibilityLabel={t('account.intro.cardOf', {
            n: index + 1,
            count: CARDS.length,
          })}
        >
          {CARDS.map((c, i) => (
            <View
              key={c.key}
              style={[
                styles.dot,
                i === index ? styles.dotActive : null,
                {
                  backgroundColor: i === index ? colors.primary : colors.border,
                },
              ]}
            />
          ))}
        </View>
        <Button
          label={
            last
              ? replay
                ? t('common.done')
                : t('account.intro.letsSetUp')
              : t('common.next')
          }
          icon="arrow-forward"
          onPress={() => (last ? leave() : goTo(index + 1))}
          testID="intro-next"
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  top: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingLeft: space.lg,
    paddingRight: space.sm,
  },
  list: { flex: 1 },
  card: {
    paddingHorizontal: space.lg,
    justifyContent: 'center',
    gap: space.xl,
  },
  demo: { alignSelf: 'stretch', alignItems: 'center' },
  stage: {
    height: 300,
    borderRadius: radius.xxl,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.lg,
  },
  body: { marginTop: space.sm, paddingHorizontal: space.md },
  footer: { paddingHorizontal: space.lg, gap: space.lg },
  dots: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: space.xs,
    alignItems: 'center',
  },
  dot: { width: 8, height: 8, borderRadius: 4 },
  dotActive: { width: 22 },
  hidden: { opacity: 0 },
  slideWrap: { alignSelf: 'stretch', gap: space.md },
  codeWrap: { alignItems: 'center', gap: space.lg },
  boxes: { flexDirection: 'row', gap: space.md },
  box: {
    width: 56,
    height: 64,
    borderRadius: radius.lg,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  paid: { alignItems: 'center', minHeight: 56 },
});
