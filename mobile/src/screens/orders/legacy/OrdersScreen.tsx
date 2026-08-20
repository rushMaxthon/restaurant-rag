import React, { useCallback, useEffect, useState } from 'react';
import {
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
  type ListRenderItem,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { OrderStepper } from '@components/OrderStepper';
import { SkeletonBlock } from '@components/SkeletonBlock';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { api, formatCurrency, formatDateTime } from '@services/api';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { Order } from '@/types/app';
import type { RootStackParamList } from '@/navigation/AppNavigator';

export function OrdersScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { token } = useSession();
  const { pushToast } = useAppActions();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(Boolean(token));

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }

    let active = true;

    const load = async () => {
      try {
        const rows = await api.getOrders(token);
        if (active) {
          setOrders(rows);
        }
      } catch (error) {
        if (active) {
          pushToast(
            'Orders unavailable',
            error instanceof Error ? error.message : 'Unable to load orders.',
            'error',
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    };

    load();
    const interval = setInterval(() => {
      load();
    }, 30000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [pushToast, token]);

  // Hoisted out of the JSX: as an inline prop this row was rebuilt on
  // every render of the surrounding component.
  const renderOrder = useCallback<ListRenderItem<Order>>(
    ({ item }) => (
      <View style={styles.card}>
        <View style={styles.header}>
          <View>
            <Text style={styles.restaurant}>{item.restaurant.name}</Text>
            <Text style={styles.meta}>{formatDateTime(item.placed_at)}</Text>
          </View>
          <Text style={styles.total}>{formatCurrency(item.total_amount)}</Text>
        </View>
        <OrderStepper status={item.status} />
      </View>
    ),
    [styles],
  );
  return (
    <FlatList
      contentContainerStyle={styles.content}
      data={orders}
      keyExtractor={item => item.id}
      renderItem={renderOrder}
      ListHeaderComponent={<Text style={styles.title}>Your orders</Text>}
      ListEmptyComponent={
        loading ? (
          <View style={styles.skeletonList}>
            <SkeletonBlock height={180} />
            <SkeletonBlock height={180} />
          </View>
        ) : (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>
              {token ? 'No orders yet.' : 'Login to track your orders.'}
            </Text>
            <Text style={styles.emptyText}>
              {token
                ? 'Placed orders will appear here with live tracking.'
                : 'Your placed orders will appear here with live status updates every 30 seconds.'}
            </Text>
            {!token ? (
              <Pressable
                onPress={() => navigation.navigate('Login')}
                style={styles.loginButton}
              >
                <Text style={styles.loginButtonText}>Login</Text>
              </Pressable>
            ) : null}
          </View>
        )
      }
      showsVerticalScrollIndicator={false}
    />
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    content: {
      padding: theme.spacing.screen,
      paddingTop: theme.spacing.stackTop,
      paddingBottom: 120,
      backgroundColor: theme.colors.background,
      gap: 14,
    },
    title: {
      color: theme.colors.text,
      fontSize: 24,
      fontWeight: '800',
      marginBottom: 12,
    },
    card: {
      borderRadius: 16,
      backgroundColor: theme.colors.card,
      padding: 16,
      marginBottom: 14,
    },
    header: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      gap: 12,
    },
    restaurant: {
      color: theme.colors.text,
      fontWeight: '800',
      fontSize: 16,
    },
    meta: {
      color: theme.colors.secondaryText,
      marginTop: 4,
    },
    total: {
      color: theme.colors.text,
      fontWeight: '800',
    },
    empty: {
      borderRadius: 16,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : '#FFF7F2',
      padding: 20,
      gap: 6,
    },
    skeletonList: {
      gap: 12,
    },
    emptyTitle: {
      color: theme.colors.text,
      fontWeight: '800',
    },
    emptyText: {
      color: theme.colors.secondaryText,
    },
    loginButton: {
      marginTop: 10,
      alignSelf: 'flex-start',
      backgroundColor: theme.colors.primary,
      borderRadius: 10,
      paddingHorizontal: 16,
      paddingVertical: 10,
    },
    loginButtonText: {
      color: theme.colors.white,
      fontWeight: '800',
    },
  });

export const styles = createStyles(theme);
