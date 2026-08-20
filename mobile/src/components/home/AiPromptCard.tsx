import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface AiPromptCardProps {
  onPress: () => void;
}

function AiPromptCardComponent({
  onPress,
}: AiPromptCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.card,
        pressed ? styles.cardPressed : null,
      ]}
    >
      <View style={styles.glowPrimary} />
      <View style={styles.glowSecondary} />

      <View style={styles.header}>
        <View style={styles.iconWrap}>
          <Icon color={theme.colors.primary} name="sparkles" size={16} />
        </View>

        <View style={styles.copy}>
          <Text style={styles.eyebrow}>AI-powered picks</Text>
          <Text style={styles.title}>Not sure what to eat?</Text>
        </View>
      </View>

      <Text style={styles.subtitle}>
        Ask AI for personalized recommendations based on your craving, budget,
        and mood.
      </Text>

      <View style={styles.footer}>
        <View style={styles.hints}>
          <View style={styles.hintPill}>
            <Text style={styles.hintText}>Spicy</Text>
          </View>
          <View style={styles.hintPill}>
            <Text style={styles.hintText}>Under Rs. 250</Text>
          </View>
        </View>

        <View style={styles.button}>
          <Text style={styles.buttonText}>Ask AI</Text>
          <Icon color={theme.colors.white} name="arrow-forward" size={13} />
        </View>
      </View>
    </Pressable>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    card: {
      borderRadius: 16,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : '#FFF5EE',
      paddingHorizontal: 13,
      paddingVertical: 12,
      gap: 9,
      overflow: 'hidden',
      borderWidth: 1,
      borderColor: 'rgba(255, 82, 0, 0.12)',
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.08,
      shadowOffset: { width: 0, height: 6 },
      shadowRadius: 14,
      elevation: 3,
    },
    cardPressed: {
      opacity: 0.96,
      transform: [{ scale: 0.99 }],
    },
    glowPrimary: {
      position: 'absolute',
      width: 104,
      height: 104,
      borderRadius: 52,
      top: -38,
      right: -14,
      backgroundColor: 'rgba(255, 82, 0, 0.12)',
    },
    glowSecondary: {
      position: 'absolute',
      width: 74,
      height: 74,
      borderRadius: 37,
      bottom: -26,
      left: -10,
      backgroundColor: 'rgba(255, 194, 160, 0.35)',
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 9,
    },
    iconWrap: {
      width: 30,
      height: 30,
      borderRadius: 15,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: 'rgba(255, 82, 0, 0.16)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    copy: {
      flex: 1,
      gap: 1,
    },
    eyebrow: {
      color: theme.colors.primary,
      fontSize: 9.5,
      fontWeight: '800',
      textTransform: 'uppercase',
      letterSpacing: 0.5,
    },
    title: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '900',
      letterSpacing: -0.3,
    },
    subtitle: {
      color: theme.colors.secondaryText,
      lineHeight: 16,
      fontSize: 11.5,
    },
    footer: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
    },
    hints: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      flex: 1,
      gap: 6,
    },
    hintPill: {
      borderRadius: 999,
      paddingHorizontal: 8,
      paddingVertical: 4,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255,255,255,0.72)',
      borderWidth: 1,
      borderColor: 'rgba(255, 82, 0, 0.10)',
    },
    hintText: {
      color: theme.colors.text,
      fontSize: 10,
      fontWeight: '700',
    },
    button: {
      minHeight: 30,
      borderRadius: 15,
      backgroundColor: theme.colors.primary,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 5,
      paddingHorizontal: 12,
      shadowColor: theme.colors.primary,
      shadowOpacity: theme.mode === 'dark' ? 0.24 : 0.18,
      shadowOffset: { width: 0, height: 3 },
      shadowRadius: 8,
      elevation: 3,
    },
    buttonText: {
      color: theme.colors.white,
      fontSize: 12,
      fontWeight: '800',
    },
  });

const styles = createStyles(theme);

/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const AiPromptCard = React.memo(AiPromptCardComponent);
