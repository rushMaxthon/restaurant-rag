import React from 'react';
import {
  ScrollView,
  StyleSheet,
  Text,
  View,
  Pressable,
  useColorScheme,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Ionicons';
import { useAppActions, useThemePreference } from '@hooks/useAppStore';
import {
  useTheme,
  useThemedStyles,
  type AppTheme,
  type ThemePreference,
} from '@/theme';

const options: Array<{
  value: ThemePreference;
  title: string;
  subtitle: string;
  icon: string;
}> = [
  {
    value: 'light',
    title: 'Light',
    subtitle: 'Bright interface with warm food-first accents',
    icon: 'sunny-outline',
  },
  {
    value: 'dark',
    title: 'Dark',
    subtitle: 'Low-glare surfaces with richer contrast at night',
    icon: 'moon-outline',
  },
  {
    value: 'system',
    title: 'System',
    subtitle: 'Automatically follows your device appearance',
    icon: 'phone-portrait-outline',
  },
];

export function AppearanceScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const systemScheme = useColorScheme();
  const themePreference = useThemePreference();
  const { setThemePreference } = useAppActions();

  const resolvedMode =
    themePreference === 'system'
      ? systemScheme === 'dark'
        ? 'Dark'
        : 'Light'
      : themePreference === 'dark'
      ? 'Dark'
      : 'Light';

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.card}>
          <Text style={styles.heading}>Appearance</Text>
          <Text style={styles.helper}>
            Choose the look you want across the app. Your selection is saved and
            applies to screens, tabs, cards, and sheets.
          </Text>

          <View style={styles.currentModeCard}>
            <View style={styles.currentModeIcon}>
              <Icon
                color={theme.colors.primary}
                name={theme.mode === 'dark' ? 'moon-outline' : 'sunny-outline'}
                size={20}
              />
            </View>
            <View style={styles.currentModeCopy}>
              <Text style={styles.currentModeTitle}>Active appearance</Text>
              <Text style={styles.currentModeSubtitle}>
                {resolvedMode} mode
                {themePreference === 'system' ? ' via System setting' : ''}
              </Text>
            </View>
            <View style={styles.activeBadge}>
              <Text style={styles.activeBadgeText}>
                {themePreference === 'system' ? 'System' : 'Selected'}
              </Text>
            </View>
          </View>

          <View style={styles.optionsColumn}>
            {options.map(option => {
              const isSelected = themePreference === option.value;
              return (
                <Pressable
                  key={option.value}
                  onPress={() => {
                    void setThemePreference(option.value);
                  }}
                  style={[
                    styles.optionCard,
                    isSelected ? styles.optionCardActive : null,
                  ]}
                >
                  <View style={styles.optionIcon}>
                    <Icon
                      color={theme.colors.primary}
                      name={option.icon}
                      size={20}
                    />
                  </View>
                  <View style={styles.optionCopy}>
                    <Text style={styles.optionTitle}>{option.title}</Text>
                    <Text style={styles.optionSubtitle}>{option.subtitle}</Text>
                  </View>
                  <View
                    style={[
                      styles.selectionIndicator,
                      isSelected ? styles.selectionIndicatorActive : null,
                    ]}
                  >
                    {isSelected ? (
                      <Icon
                        color={theme.colors.white}
                        name="checkmark"
                        size={14}
                      />
                    ) : null}
                  </View>
                </Pressable>
              );
            })}
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
      backgroundColor: theme.colors.surface,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 18,
      gap: 16,
    },
    heading: { color: theme.colors.text, fontSize: 22, fontWeight: '800' },
    helper: { color: theme.colors.secondaryText, lineHeight: 20 },
    currentModeCard: {
      borderRadius: 20,
      backgroundColor: theme.colors.cream,
      padding: 16,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    currentModeIcon: {
      width: 42,
      height: 42,
      borderRadius: 21,
      backgroundColor: theme.colors.surface,
      alignItems: 'center',
      justifyContent: 'center',
    },
    currentModeCopy: { flex: 1, gap: 4 },
    currentModeTitle: { color: theme.colors.text, fontWeight: '800' },
    currentModeSubtitle: { color: theme.colors.secondaryText, fontSize: 12 },
    activeBadge: {
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
      paddingHorizontal: 10,
      paddingVertical: 7,
    },
    activeBadgeText: {
      color: theme.colors.primary,
      fontWeight: '800',
      fontSize: 12,
    },
    optionsColumn: {
      gap: 12,
    },
    optionCard: {
      borderRadius: 20,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.background,
      padding: 16,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    optionCardActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    optionIcon: {
      width: 42,
      height: 42,
      borderRadius: 21,
      backgroundColor: theme.colors.surface,
      alignItems: 'center',
      justifyContent: 'center',
    },
    optionCopy: {
      flex: 1,
      gap: 4,
    },
    optionTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    optionSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    selectionIndicator: {
      width: 22,
      height: 22,
      borderRadius: 11,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surface,
      alignItems: 'center',
      justifyContent: 'center',
    },
    selectionIndicatorActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primary,
    },
  });
