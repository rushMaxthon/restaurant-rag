import React, { useCallback, useState } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';
import Animated, { FadeInDown } from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { CountdownRing } from '@components/ui/CountdownRing';
import { OnlineToggle } from '@components/ui/OnlineToggle';
import { Skeleton } from '@components/ui/Skeleton';
import { SlideToConfirm } from '@components/ui/SlideToConfirm';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';

const OFFER_MS = 30_000;

/**
 * A development-only screen: every building block, live, so its feel can be
 * judged on a real phone before a screen is built from it. Replaced by Home
 * once login exists; kept reachable in debug builds after that.
 */
export function ComponentGalleryScreen() {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();
  const [online, setOnline] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [expiresAt, setExpiresAt] = useState(() => Date.now() + OFFER_MS);
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);

  const toggle = useCallback((next: boolean) => {
    setToggling(true);
    setTimeout(() => {
      setOnline(next);
      setToggling(false);
    }, 700);
  }, []);

  const confirm = useCallback(() => {
    setBusy(true);
    setTimeout(() => {
      setBusy(false);
      setStep(s => s + 1);
    }, 900);
  }, []);

  const steps = ['Slide to pick up', 'Slide to deliver', 'Slide to start again'];

  return (
    <ScrollView
      style={{ backgroundColor: colors.bg }}
      contentContainerStyle={[styles.content, { paddingTop: insets.top + space.lg, paddingBottom: insets.bottom + space.huge }]}
    >
      <Animated.View entering={FadeInDown.duration(400)}>
        <AppText variant="micro" tone="primary">RIDER · PREVIEW</AppText>
        <AppText variant="title" style={styles.gap}>Building blocks</AppText>
        <AppText tone="muted">Tap, slide and watch. Everything here runs on the UI thread.</AppText>
      </Animated.View>

      <Section title="Shift" index={1}>
        <OnlineToggle online={online} onChange={toggle} busy={toggling} />
        <AppText variant="caption" tone="muted" align="center" style={styles.gap}>
          {online ? 'You will get new orders nearby.' : 'You are not getting orders.'}
        </AppText>
      </Section>

      <Section title="New order countdown" index={2}>
        <View style={styles.center}>
          <CountdownRing expiresAt={expiresAt} totalMs={OFFER_MS} />
        </View>
        <Button kind="secondary" size="md" icon="refresh" label="Restart countdown" onPress={() => setExpiresAt(Date.now() + OFFER_MS)} style={styles.gap} />
      </Section>

      <Section title="Trip step" index={3}>
        <SlideToConfirm
          label={steps[step % steps.length] ?? ''}
          tone={step % 2 === 0 ? 'primary' : 'success'}
          busy={busy}
          resetKey={step}
          onConfirm={confirm}
        />
        <View style={styles.gap} />
        <SlideToConfirm label="Slide to deliver" onConfirm={() => undefined} disabledReason="Enter the customer's 4-digit code first" />
      </Section>

      <Section title="Buttons" index={4}>
        <Button label="Accept order" icon="checkmark-circle" />
        <Button kind="secondary" label="Navigate" icon="navigate" style={styles.gap} />
        <Button kind="danger" label="Customer unavailable" icon="alert-circle" style={styles.gap} />
        <Button label="Go online" disabledReason="Allow location 'all the time' to receive orders" style={styles.gap} />
      </Section>

      <Section title="Loading" index={5}>
        <View style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Skeleton width="40%" height={14} />
          <Skeleton height={22} style={styles.gap} />
          <Skeleton width="70%" height={14} style={styles.gap} />
        </View>
      </Section>
    </ScrollView>
  );
}

function Section({ title, index, children }: { title: string; index: number; children: React.ReactNode }) {
  const { colors } = useTheme();
  return (
    <Animated.View
      entering={FadeInDown.delay(80 * index).springify().damping(18)}
      style={[styles.section, { backgroundColor: colors.surface, borderColor: colors.border }]}
    >
      <AppText variant="label" tone="muted" style={styles.sectionTitle}>
        {title}
      </AppText>
      {children}
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  content: { paddingHorizontal: space.lg, gap: space.lg },
  gap: { marginTop: space.sm },
  center: { alignItems: 'center' },
  section: { borderRadius: radius.xl, borderWidth: 1, padding: space.lg },
  sectionTitle: { marginBottom: space.md },
  card: { borderRadius: radius.lg, borderWidth: 1, padding: space.lg },
});
