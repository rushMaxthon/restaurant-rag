import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { api } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

function SettingToggle({
  title,
  subtitle,
  value,
  onValueChange,
  trackColor,
  theme,
  styles,
  footnote,
  disabled,
  busy,
}: {
  title: string;
  subtitle: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  trackColor: { false: string; true: string };
  theme: AppTheme;
  styles: ReturnType<typeof createStyles>;
  /** A second line under the subtitle — when the choice was last made. */
  footnote?: string | null;
  disabled?: boolean;
  busy?: boolean;
}) {
  return (
    <View style={styles.settingRow}>
      <View style={styles.settingCopy}>
        <Text style={styles.settingTitle}>{title}</Text>
        <Text style={styles.settingSubtitle}>{subtitle}</Text>
        {footnote ? <Text style={styles.settingFootnote}>{footnote}</Text> : null}
      </View>
      {busy ? (
        <ActivityIndicator color={theme.colors.primary} />
      ) : (
        <Switch
          disabled={disabled}
          onValueChange={onValueChange}
          thumbColor={theme.colors.white}
          trackColor={trackColor}
          value={value}
        />
      )}
    </View>
  );
}

export function NotificationSettingsScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const switchTrackColor = {
    false: theme.mode === 'dark' ? theme.colors.surfaceAlt : '#D7D8DE',
    true: theme.mode === 'dark' ? theme.tone('#CC6A40') : theme.tone('#FF9A6A'),
  };
  const { token } = useSession();
  const { pushToast } = useAppActions();

  // Order alerts and AI suggestions are still local-only: nothing persists them
  // and no endpoint backs them yet. Promotions is different — it is the
  // customer's marketing consent, a legal record, and it used to be local state
  // too: someone could switch it off, believe they had opted out, and keep
  // receiving campaigns.
  const [orderAlerts, setOrderAlerts] = useState(true);
  const [aiTips, setAiTips] = useState(false);

  const [promotions, setPromotions] = useState(true);
  const [consentChangedAt, setConsentChangedAt] = useState<string | null>(null);
  const [consentLoaded, setConsentLoaded] = useState(false);
  const [consentSaving, setConsentSaving] = useState(false);

  useEffect(() => {
    if (!token) {
      return;
    }
    let active = true;
    api
      .getMarketingConsent(token)
      .then(consent => {
        if (!active) return;
        setPromotions(consent.marketing_opt_in);
        setConsentChangedAt(consent.marketing_opt_in_changed_at);
        setConsentLoaded(true);
      })
      .catch(() => {
        // The switch stays disabled rather than showing a guess. Rendering it
        // as "off" would tell the customer they had opted out when the server
        // may say the opposite.
        if (active) setConsentLoaded(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  /**
   * Opt in or out, saved the moment it is tapped.
   *
   * Deliberately not behind a save button: withdrawing consent has to be at
   * least as easy as giving it. The switch moves first and rolls back if the
   * server refuses, so it always shows what is actually stored.
   */
  const handlePromotionsChange = useCallback(
    (next: boolean) => {
      if (!token) {
        return;
      }
      const previous = promotions;
      setPromotions(next);
      setConsentSaving(true);
      api
        .updateMarketingConsent(token, next)
        .then(consent => {
          setPromotions(consent.marketing_opt_in);
          setConsentChangedAt(consent.marketing_opt_in_changed_at);
        })
        .catch(() => {
          setPromotions(previous);
          pushToast(
            'Not saved',
            'We could not change that just now. Please try again.',
            'error',
          );
        })
        .finally(() => setConsentSaving(false));
    },
    [promotions, pushToast, token],
  );

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.card}>
          <Text style={styles.heading}>Notification settings</Text>
          <Text style={styles.helper}>
            Choose the alerts that are actually useful to you.
          </Text>
          <SettingToggle
            onValueChange={setOrderAlerts}
            subtitle="Delivery progress, preparation status, and drop updates"
            styles={styles}
            theme={theme}
            trackColor={switchTrackColor}
            title="Order alerts"
            value={orderAlerts}
          />
          <SettingToggle
            busy={consentSaving}
            disabled={!consentLoaded}
            footnote={
              !consentLoaded
                ? 'We cannot load this right now.'
                : consentChangedAt
                  ? `You chose this on ${new Date(consentChangedAt).toLocaleDateString()}.`
                  : // Null means nobody ever asked: existing accounts were
                    // brought in switched on. Saying so is more honest than
                    // showing a date that was never a decision.
                    "You haven't changed this yet."
            }
            onValueChange={handlePromotionsChange}
            subtitle="Discounts, offers, and occasional restaurant promos. Order updates are not affected."
            styles={styles}
            theme={theme}
            trackColor={switchTrackColor}
            title="Promotions"
            value={promotions}
          />
          <SettingToggle
            onValueChange={setAiTips}
            subtitle="Helpful nudges from the AI assistant based on cravings"
            styles={styles}
            theme={theme}
            trackColor={switchTrackColor}
            title="AI suggestions"
            value={aiTips}
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: { flex: 1, backgroundColor: theme.colors.background },
    content: {
      padding: theme.spacing.screen,
      paddingTop: theme.spacing.stackTop,
      paddingBottom: 120,
    },
    card: {
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 18,
      gap: 16,
    },
    heading: { color: theme.colors.text, fontSize: 22, fontWeight: '800' },
    helper: { color: theme.colors.secondaryText, lineHeight: 20 },
    settingRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      paddingVertical: 6,
    },
    settingCopy: { flex: 1, gap: 4 },
    settingTitle: { color: theme.colors.text, fontSize: 15, fontWeight: '800' },
    settingSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    settingFootnote: {
      color: theme.colors.hint,
      fontSize: 11,
      lineHeight: 16,
    },
  });
