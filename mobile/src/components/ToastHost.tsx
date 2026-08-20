import React, { useEffect, useMemo, useRef } from 'react';
import {
  Animated,
  Easing,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { ToastMessage } from '@/types/app';

interface ToastHostProps {
  toasts: ToastMessage[];
  onDismiss: (id: number) => void;
}

interface ToastCardProps {
  toast: ToastMessage;
  onDismiss: (id: number) => void;
}

function getToastPalette(theme: AppTheme, tone: ToastMessage['tone']) {
  switch (tone) {
    case 'success':
      return {
        icon: 'checkmark-circle',
        iconColor: theme.colors.success,
        iconBg: theme.colors.successSoft,
        cardBg: theme.mode === 'dark' ? theme.colors.surfaceAlt : '#F1FBF5',
        borderColor:
          theme.mode === 'dark'
            ? theme.colors.border
            : 'rgba(72, 196, 121, 0.26)',
        accentColor: theme.colors.success,
      };
    case 'error':
      return {
        icon: 'close-circle',
        iconColor: theme.colors.deepRed,
        iconBg: theme.colors.dangerSoft,
        cardBg: theme.mode === 'dark' ? theme.colors.surfaceAlt : '#FFF4F5',
        borderColor:
          theme.mode === 'dark'
            ? theme.colors.border
            : 'rgba(203, 32, 45, 0.22)',
        accentColor: theme.colors.deepRed,
      };
    default:
      return {
        icon: 'information-circle',
        iconColor: theme.colors.primary,
        iconBg: theme.colors.primarySoft,
        cardBg: theme.mode === 'dark' ? theme.colors.surfaceAlt : '#FFF7F1',
        borderColor:
          theme.mode === 'dark'
            ? theme.colors.border
            : 'rgba(255, 82, 0, 0.22)',
        accentColor: theme.colors.primary,
      };
  }
}

function ToastCard({ toast, onDismiss }: ToastCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const palette = useMemo(
    () => getToastPalette(theme, toast.tone),
    [theme, toast.tone],
  );
  const translateY = useRef(new Animated.Value(-16)).current;
  const opacity = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(translateY, {
        toValue: 0,
        duration: 260,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(opacity, {
        toValue: 1,
        duration: 220,
        easing: Easing.out(Easing.ease),
        useNativeDriver: true,
      }),
    ]).start();
  }, [opacity, translateY]);

  return (
    <Animated.View
      style={[
        styles.cardWrap,
        {
          opacity,
          transform: [{ translateY }],
        },
      ]}
    >
      <Pressable
        onPress={() => onDismiss(toast.id)}
        style={[
          styles.card,
          {
            backgroundColor: palette.cardBg,
            borderColor: palette.borderColor,
          },
        ]}
      >
        <View
          style={[
            styles.iconWrap,
            {
              backgroundColor: palette.iconBg,
            },
          ]}
        >
          <Icon color={palette.iconColor} name={palette.icon} size={20} />
        </View>

        <View style={styles.copy}>
          <View
            style={[
              styles.accentPill,
              {
                backgroundColor: palette.accentColor,
              },
            ]}
          />
          <Text numberOfLines={2} style={styles.title}>
            {toast.title}
          </Text>
          <Text style={styles.description}>{toast.description}</Text>
        </View>
      </Pressable>
    </Animated.View>
  );
}

export function ToastHost({
  toasts,
  onDismiss,
}: ToastHostProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const insets = useSafeAreaInsets();
  const topOffset = Math.max(insets.top + 8, 16);

  return (
    <View
      pointerEvents="box-none"
      style={[styles.container, { top: topOffset }]}
    >
      {toasts.map(toast => (
        <ToastCard key={toast.id} onDismiss={onDismiss} toast={toast} />
      ))}
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    container: {
      position: 'absolute',
      left: 16,
      right: 16,
      gap: 10,
      zIndex: 50,
    },
    cardWrap: {
      width: '100%',
    },
    card: {
      minHeight: 64,
      borderRadius: 18,
      borderWidth: 1,
      paddingHorizontal: 12,
      paddingVertical: 12,
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 10,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.1,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 18,
      elevation: 8,
    },
    iconWrap: {
      width: 32,
      height: 32,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 1,
    },
    copy: {
      flex: 1,
      minWidth: 0,
    },
    accentPill: {
      width: 28,
      height: 3,
      borderRadius: 999,
      marginBottom: 7,
    },
    title: {
      color: theme.colors.text,
      fontSize: 15,
      lineHeight: 19,
      fontWeight: '900',
      marginBottom: 2,
    },
    description: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 18,
      flexShrink: 1,
    },
  });

const styles = createStyles(theme);
