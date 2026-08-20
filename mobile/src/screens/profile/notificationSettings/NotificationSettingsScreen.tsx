import React, { useState } from 'react';
import { ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

function SettingToggle({
  title,
  subtitle,
  value,
  onValueChange,
  trackColor,
  theme,
  styles,
}: {
  title: string;
  subtitle: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  trackColor: { false: string; true: string };
  theme: AppTheme;
  styles: ReturnType<typeof createStyles>;
}) {
  return (
    <View style={styles.settingRow}>
      <View style={styles.settingCopy}>
        <Text style={styles.settingTitle}>{title}</Text>
        <Text style={styles.settingSubtitle}>{subtitle}</Text>
      </View>
      <Switch
        onValueChange={onValueChange}
        thumbColor={theme.colors.white}
        trackColor={trackColor}
        value={value}
      />
    </View>
  );
}

export function NotificationSettingsScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const switchTrackColor = {
    false: theme.mode === 'dark' ? theme.colors.surfaceAlt : '#D7D8DE',
    true: theme.mode === 'dark' ? '#CC6A40' : '#FF9A6A',
  };
  const [orderAlerts, setOrderAlerts] = useState(true);
  const [promotions, setPromotions] = useState(true);
  const [aiTips, setAiTips] = useState(false);

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
            onValueChange={setPromotions}
            subtitle="Discounts, offers, and occasional restaurant promos"
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
  });

export const styles = createStyles(theme);
