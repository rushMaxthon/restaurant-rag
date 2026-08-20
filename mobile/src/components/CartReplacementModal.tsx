import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface CartReplacementModalProps {
  visible: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function CartReplacementModal({
  visible,
  onCancel,
  onConfirm,
}: CartReplacementModalProps): React.JSX.Element | null {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const [mounted, setMounted] = useState(visible);
  const backdrop = useRef(new Animated.Value(visible ? 1 : 0)).current;
  const sheet = useRef(new Animated.Value(visible ? 1 : 0)).current;

  useEffect(() => {
    if (visible) {
      setMounted(true);
    }

    Animated.parallel([
      Animated.timing(backdrop, {
        toValue: visible ? 1 : 0,
        duration: visible ? 180 : 140,
        easing: Easing.out(Easing.ease),
        useNativeDriver: true,
      }),
      Animated.spring(sheet, {
        toValue: visible ? 1 : 0,
        damping: 18,
        mass: 0.9,
        stiffness: 180,
        useNativeDriver: true,
      }),
    ]).start(({ finished }) => {
      if (finished && !visible) {
        setMounted(false);
      }
    });
  }, [backdrop, sheet, visible]);

  const sheetStyle = useMemo(
    () => ({
      opacity: sheet,
      transform: [
        {
          translateY: sheet.interpolate({
            inputRange: [0, 1],
            outputRange: [28, 0],
          }),
        },
        {
          scale: sheet.interpolate({
            inputRange: [0, 1],
            outputRange: [0.96, 1],
          }),
        },
      ],
    }),
    [sheet],
  );

  if (!mounted) {
    return null;
  }

  return (
    <Modal
      animationType="none"
      onRequestClose={onCancel}
      transparent
      visible={mounted}
    >
      <View style={styles.root}>
        <Animated.View style={[styles.backdrop, { opacity: backdrop }]}>
          <Pressable onPress={onCancel} style={StyleSheet.absoluteFill} />
        </Animated.View>

        <View pointerEvents="box-none" style={styles.centerWrap}>
          <Animated.View style={[styles.card, sheetStyle]}>
            <View style={styles.badge}>
              <Text style={styles.badgeText}>Cart</Text>
            </View>
            <Text style={styles.title}>Replace cart items?</Text>
            <Text style={styles.message}>
              Your cart already has items from another restaurant. Do you want
              to clear your current cart and add this item?
            </Text>

            <View style={styles.actions}>
              <Pressable onPress={onCancel} style={styles.secondaryButton}>
                <Text style={styles.secondaryButtonText}>Cancel</Text>
              </Pressable>
              <Pressable onPress={onConfirm} style={styles.primaryButton}>
                <Text style={styles.primaryButtonText}>Clear & Add</Text>
              </Pressable>
            </View>
          </Animated.View>
        </View>
      </View>
    </Modal>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    root: {
      flex: 1,
      justifyContent: 'center',
      paddingHorizontal: 24,
    },
    backdrop: {
      ...StyleSheet.absoluteFill,
      backgroundColor: 'rgba(18, 22, 33, 0.38)',
    },
    centerWrap: {
      justifyContent: 'center',
    },
    card: {
      borderRadius: 28,
      backgroundColor: theme.colors.surfaceRaised,
      paddingHorizontal: 22,
      paddingVertical: 22,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.22,
      shadowOffset: { width: 0, height: 18 },
      shadowRadius: 30,
      elevation: 14,
      gap: 12,
    },
    badge: {
      alignSelf: 'flex-start',
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
      paddingHorizontal: 10,
      paddingVertical: 6,
    },
    badgeText: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '800',
      letterSpacing: 0.3,
      textTransform: 'uppercase',
    },
    title: {
      color: theme.colors.text,
      fontSize: 24,
      lineHeight: 30,
      fontWeight: '900',
    },
    message: {
      color: theme.colors.secondaryText,
      fontSize: 15,
      lineHeight: 23,
    },
    actions: {
      flexDirection: 'row',
      gap: 12,
      marginTop: 4,
    },
    secondaryButton: {
      flex: 1,
      minHeight: 50,
      borderRadius: 16,
      borderWidth: 1,
      borderColor: theme.colors.border,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
    },
    secondaryButtonText: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    primaryButton: {
      flex: 1,
      minHeight: 50,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
    },
    primaryButtonText: {
      color: theme.colors.white,
      fontSize: 15,
      fontWeight: '800',
    },
  });

const styles = createStyles(theme);
