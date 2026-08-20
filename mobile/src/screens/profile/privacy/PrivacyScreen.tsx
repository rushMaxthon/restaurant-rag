import React, { useState } from 'react';
import { ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

export function PrivacyScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const switchTrackColor = {
    false: theme.mode === 'dark' ? theme.colors.surfaceAlt : '#D7D8DE',
    true: theme.mode === 'dark' ? '#CC6A40' : '#FF9A6A',
  };
  const [shareUsage, setShareUsage] = useState(true);
  const [saveChatHistory, setSaveChatHistory] = useState(true);

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.card}>
          <Text style={styles.heading}>Privacy controls</Text>
          <Text style={styles.helper}>
            Review how your preferences and chat context are used inside the
            app.
          </Text>

          <View style={styles.row}>
            <View style={styles.copy}>
              <Text style={styles.title}>Personalized usage insights</Text>
              <Text style={styles.subtitle}>
                Help improve recommendations using anonymous behavioral signals.
              </Text>
            </View>
            <Switch
              onValueChange={setShareUsage}
              thumbColor={theme.colors.white}
              trackColor={switchTrackColor}
              value={shareUsage}
            />
          </View>

          <View style={styles.row}>
            <View style={styles.copy}>
              <Text style={styles.title}>Save AI chat history</Text>
              <Text style={styles.subtitle}>
                Keep prior AI conversations for continuity and follow-up
                suggestions.
              </Text>
            </View>
            <Switch
              onValueChange={setSaveChatHistory}
              thumbColor={theme.colors.white}
              trackColor={switchTrackColor}
              value={saveChatHistory}
            />
          </View>
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
    row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
    copy: { flex: 1, gap: 4 },
    title: { color: theme.colors.text, fontSize: 15, fontWeight: '800' },
    subtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
  });

export const styles = createStyles(theme);
