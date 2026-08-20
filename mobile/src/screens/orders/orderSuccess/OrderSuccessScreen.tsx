import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import {
  CommonActions,
  useNavigation,
  useRoute,
} from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/AppNavigator';

type OrderSuccessRoute = RouteProp<RootStackParamList, 'OrderSuccess'>;
type OrderSuccessNav = NativeStackNavigationProp<RootStackParamList>;

export function OrderSuccessScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation<OrderSuccessNav>();
  const route = useRoute<OrderSuccessRoute>();
  const orderId = route.params?.orderId;

  const goHome = () => {
    navigation.dispatch(
      CommonActions.reset({
        index: 0,
        routes: [{ name: 'MainTabs', params: { screen: 'Home' } }],
      }),
    );
  };

  const goToOrders = () => {
    navigation.dispatch(
      CommonActions.reset({
        index: 1,
        routes: [
          { name: 'MainTabs', params: { screen: 'Orders' } },
          { name: 'OrderList' },
        ],
      }),
    );
  };

  return (
    <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
      <View style={styles.screen}>
        <View style={styles.heroCard}>
          <View style={styles.glowPrimary} />
          <View style={styles.glowSecondary} />
          <View style={styles.successBadge}>
            <Icon color={theme.colors.white} name="checkmark" size={34} />
          </View>
          <Text style={styles.title}>Order Placed Successfully</Text>
          <Text style={styles.subtitle}>
            Your order is being prepared. We&apos;ll keep the latest status
            ready in your order history.
          </Text>
          {orderId ? (
            <View style={styles.orderIdPill}>
              <Text style={styles.orderIdLabel}>Order reference</Text>
              <Text numberOfLines={1} style={styles.orderIdValue}>
                #{orderId.slice(0, 8).toUpperCase()}
              </Text>
            </View>
          ) : null}
        </View>

        <View style={styles.noteCard}>
          <Text style={styles.noteTitle}>What happens next?</Text>
          <Text style={styles.noteText}>
            The restaurant has received your request. You can head home to keep
            browsing or open orders to track progress.
          </Text>
        </View>

        <View style={styles.actions}>
          <Pressable onPress={goHome} style={styles.primaryButton}>
            <Text style={styles.primaryButtonText}>Go to Home</Text>
          </Pressable>
          <Pressable onPress={goToOrders} style={styles.secondaryButton}>
            <Text style={styles.secondaryButtonText}>View Orders</Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    screen: {
      flex: 1,
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 20,
      paddingBottom: 24,
      justifyContent: 'center',
      gap: 18,
    },
    heroCard: {
      borderRadius: 30,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceRaised : '#FFF4EC',
      paddingHorizontal: 22,
      paddingVertical: 24,
      alignItems: 'center',
      gap: 14,
      overflow: 'hidden',
      position: 'relative',
    },
    glowPrimary: {
      position: 'absolute',
      width: 180,
      height: 180,
      borderRadius: 90,
      top: -56,
      right: -22,
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(255, 122, 69, 0.08)'
          : 'rgba(255,82,0,0.10)',
    },
    glowSecondary: {
      position: 'absolute',
      width: 120,
      height: 120,
      borderRadius: 60,
      bottom: -42,
      left: -18,
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(255, 122, 69, 0.06)'
          : 'rgba(255,189,153,0.30)',
    },
    successBadge: {
      width: 82,
      height: 82,
      borderRadius: 41,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      shadowColor: theme.colors.primary,
      shadowOpacity: 0.2,
      shadowOffset: { width: 0, height: 10 },
      shadowRadius: 18,
      elevation: 8,
    },
    title: {
      color: theme.colors.text,
      fontSize: 30,
      lineHeight: 36,
      fontWeight: '900',
      textAlign: 'center',
    },
    subtitle: {
      color: theme.colors.secondaryText,
      fontSize: 15,
      lineHeight: 23,
      textAlign: 'center',
    },
    orderIdPill: {
      borderRadius: 18,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255,255,255,0.72)',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.6)',
      paddingHorizontal: 14,
      paddingVertical: 10,
      alignItems: 'center',
      gap: 2,
      maxWidth: '100%',
    },
    orderIdLabel: {
      color: theme.colors.hint,
      fontSize: 11,
      fontWeight: '700',
    },
    orderIdValue: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    noteCard: {
      borderRadius: 22,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 18,
      gap: 8,
    },
    noteTitle: {
      color: theme.colors.text,
      fontSize: 17,
      fontWeight: '800',
    },
    noteText: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 21,
    },
    actions: {
      gap: 12,
    },
    primaryButton: {
      minHeight: 54,
      borderRadius: 20,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    primaryButtonText: {
      color: theme.colors.white,
      fontSize: 16,
      fontWeight: '800',
    },
    secondaryButton: {
      minHeight: 54,
      borderRadius: 20,
      borderWidth: 1,
      borderColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
    },
    secondaryButtonText: {
      color: theme.colors.primary,
      fontSize: 16,
      fontWeight: '800',
    },
  });

export const styles = createStyles(theme);
