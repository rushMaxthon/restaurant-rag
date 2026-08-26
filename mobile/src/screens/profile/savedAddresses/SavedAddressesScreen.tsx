import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import {
  useAppActions,
  useSelectedLocation,
  useSession,
} from '@hooks/useAppStore';
import { ApiError, api } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/navigationTypes';
import type { SavedAddress } from '@/types/app';
import {
  buildSavedAddressSubtitle,
  mapSavedAddressToSelectedLocation,
  savedAddressLabelCopy,
} from './addressUtils';

type Navigation = NativeStackNavigationProp<
  RootStackParamList,
  'SavedAddresses'
>;

function areSavedAddressListsEqual(
  left: SavedAddress[],
  right: SavedAddress[],
): boolean {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((item, index) => {
    const next = right[index];
    return (
      item.id === next.id &&
      item.label === next.label &&
      item.formatted_address === next.formatted_address &&
      item.phone_number === next.phone_number &&
      item.is_default === next.is_default &&
      item.updated_at === next.updated_at
    );
  });
}

export function SavedAddressesScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation<Navigation>();
  const { token, user } = useSession();
  const selectedLocation = useSelectedLocation();
  const { updateUser, setSelectedLocation, pushToast } = useAppActions();
  const [addresses, setAddresses] = useState<SavedAddress[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busyAddressId, setBusyAddressId] = useState<string | null>(null);

  const loadAddresses = useCallback(
    async (mode: 'initial' | 'refresh' = 'initial') => {
      if (!token) {
        setAddresses([]);
        setLoading(false);
        setRefreshing(false);
        return;
      }

      if (mode === 'initial') {
        setLoading(true);
      } else {
        setRefreshing(true);
      }

      try {
        const rows = await api.getSavedAddresses(token);
        setAddresses(current =>
          areSavedAddressListsEqual(current, rows) ? current : rows,
        );
      } catch (error) {
        const message =
          error instanceof ApiError
            ? error.message
            : 'Unable to load saved addresses right now.';
        pushToast('Addresses unavailable', message, 'error');
      } finally {
        if (mode === 'initial') {
          setLoading(false);
        } else {
          setRefreshing(false);
        }
      }
    },
    [pushToast, token],
  );

  useFocusEffect(
    useCallback(() => {
      void loadAddresses('initial');
    }, [loadAddresses]),
  );

  useEffect(() => {
    const defaultAddress =
      addresses.find(address => address.is_default) ?? null;
    if (!defaultAddress) {
      if (user?.default_address) {
        updateUser({ ...user, default_address: null });
      }
      if (selectedLocation?.isDefault) {
        setSelectedLocation(null);
      }
      return;
    }

    if (user && user.default_address !== defaultAddress.formatted_address) {
      updateUser({
        ...user,
        default_address: defaultAddress.formatted_address,
      });
    }

    const nextSelectedLocation =
      mapSavedAddressToSelectedLocation(defaultAddress);
    const shouldSyncSelectedLocation =
      !selectedLocation ||
      selectedLocation.isDefault ||
      selectedLocation.savedAddressId === defaultAddress.id;
    const selectedLocationChanged =
      !selectedLocation ||
      selectedLocation.address !== nextSelectedLocation.address ||
      selectedLocation.city !== nextSelectedLocation.city ||
      (selectedLocation.savedAddressId ?? null) !==
        (nextSelectedLocation.savedAddressId ?? null) ||
      (selectedLocation.label ?? null) !==
        (nextSelectedLocation.label ?? null) ||
      (selectedLocation.phoneNumber ?? null) !==
        (nextSelectedLocation.phoneNumber ?? null) ||
      Boolean(selectedLocation.isDefault) !==
        Boolean(nextSelectedLocation.isDefault);

    if (shouldSyncSelectedLocation && selectedLocationChanged) {
      setSelectedLocation(nextSelectedLocation);
    }
  }, [addresses, selectedLocation, setSelectedLocation, updateUser, user]);

  const setDefault = async (address: SavedAddress) => {
    if (!token || address.is_default) {
      return;
    }

    setBusyAddressId(address.id);
    try {
      const updated = await api.setDefaultSavedAddress(token, address.id);
      setAddresses(current =>
        current.map(item =>
          item.id === updated.id
            ? updated
            : {
                ...item,
                is_default: false,
              },
        ),
      );
      updateUser({
        ...(user as NonNullable<typeof user>),
        default_address: updated.formatted_address,
      });
      setSelectedLocation(mapSavedAddressToSelectedLocation(updated));
      pushToast(
        'Default address updated',
        `${
          savedAddressLabelCopy[updated.label]
        } will be used for delivery by default.`,
        'success',
      );
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : 'Unable to change the default address.';
      pushToast('Update failed', message, 'error');
    } finally {
      setBusyAddressId(null);
    }
  };

  const confirmDelete = (address: SavedAddress) => {
    Alert.alert(
      'Delete address?',
      'This saved address will be removed from your profile.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: () => {
            void deleteAddress(address);
          },
        },
      ],
    );
  };

  const deleteAddress = async (address: SavedAddress) => {
    if (!token) {
      return;
    }

    setBusyAddressId(address.id);
    try {
      await api.deleteSavedAddress(token, address.id);
      const remainingBase = addresses.filter(item => item.id !== address.id);
      const fallbackDefaultId =
        address.is_default && remainingBase.length > 0
          ? remainingBase[0].id
          : null;
      const remaining = remainingBase.map(item => ({
        ...item,
        is_default:
          item.is_default ||
          (fallbackDefaultId !== null && item.id === fallbackDefaultId),
      }));
      setAddresses(remaining);

      const nextDefault =
        remaining.find(item => item.is_default) ?? remaining[0] ?? null;
      if (nextDefault) {
        updateUser({
          ...(user as NonNullable<typeof user>),
          default_address: nextDefault.formatted_address,
        });
        if (
          selectedLocation?.savedAddressId === address.id ||
          selectedLocation?.isDefault
        ) {
          setSelectedLocation(mapSavedAddressToSelectedLocation(nextDefault));
        }
      } else {
        if (user?.default_address) {
          updateUser({ ...user, default_address: null });
        }
        if (
          selectedLocation?.savedAddressId === address.id ||
          selectedLocation?.isDefault
        ) {
          setSelectedLocation(null);
        }
      }

      pushToast(
        'Address deleted',
        'Your saved addresses list is updated.',
        'success',
      );
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : 'Unable to delete this address.';
      pushToast('Delete failed', message, 'error');
    } finally {
      setBusyAddressId(null);
    }
  };

  const renderEmptyState = () => (
    <View style={styles.emptyState}>
      <View style={styles.emptyIcon}>
        <Icon color={theme.colors.primary} name="location-outline" size={26} />
      </View>
      <Text style={styles.emptyTitle}>No saved addresses yet</Text>
      <Text style={styles.emptyText}>
        Add your home, work, or another frequent delivery location for faster
        checkout.
      </Text>
      <Pressable
        onPress={() =>
          navigation.navigate('SavedAddressEditor', { mode: 'create' })
        }
        style={styles.primaryAction}
      >
        <Text style={styles.primaryActionText}>Add new address</Text>
      </Pressable>
    </View>
  );

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={
          <RefreshControl
            onRefresh={() => {
              void loadAddresses('refresh');
            }}
            refreshing={refreshing}
            tintColor={theme.colors.primary}
          />
        }
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.hero}>
          <View style={styles.heroCopy}>
            <Text style={styles.heading}>Saved addresses</Text>
            <Text style={styles.helper}>
              Manage multiple delivery spots and keep one default address ready
              for checkout.
            </Text>
          </View>
          <Pressable
            onPress={() =>
              navigation.navigate('SavedAddressEditor', { mode: 'create' })
            }
            style={styles.heroButton}
          >
            <Icon color={theme.colors.onPrimary} name="add" size={18} />
            <Text style={styles.heroButtonText}>Add new</Text>
          </Pressable>
        </View>

        {loading ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={theme.colors.primary} />
            <Text style={styles.loadingText}>
              Loading your saved addresses…
            </Text>
          </View>
        ) : addresses.length === 0 ? (
          renderEmptyState()
        ) : (
          <View style={styles.list}>
            {addresses.map(address => {
              const busy = busyAddressId === address.id;
              const selected = selectedLocation?.savedAddressId === address.id;
              return (
                <View
                  key={address.id}
                  style={[
                    styles.addressCard,
                    address.is_default ? styles.addressCardDefault : null,
                    selected ? styles.addressCardSelected : null,
                  ]}
                >
                  <View style={styles.cardHeader}>
                    <View style={styles.cardHeaderLeft}>
                      <View style={styles.iconShell}>
                        <Icon
                          color={theme.colors.primary}
                          name={
                            address.label === 'HOME'
                              ? 'home-outline'
                              : address.label === 'WORK'
                              ? 'briefcase-outline'
                              : 'pin-outline'
                          }
                          size={18}
                        />
                      </View>
                      <View style={styles.cardTitleWrap}>
                        <View style={styles.badgeRow}>
                          <Text style={styles.cardTitle}>
                            {savedAddressLabelCopy[address.label]}
                          </Text>
                          {address.is_default ? (
                            <View style={styles.defaultBadge}>
                              <Text style={styles.defaultBadgeText}>
                                Default
                              </Text>
                            </View>
                          ) : null}
                        </View>
                        <Text style={styles.cardAddress}>
                          {address.formatted_address}
                        </Text>
                        {buildSavedAddressSubtitle(address) ? (
                          <Text style={styles.cardMeta}>
                            {buildSavedAddressSubtitle(address)}
                          </Text>
                        ) : null}
                        {address.phone_number ? (
                          <Text style={styles.cardMeta}>
                            {address.phone_number}
                          </Text>
                        ) : null}
                      </View>
                    </View>
                    {selected ? (
                      <Icon
                        color={theme.colors.success}
                        name="checkmark-circle"
                        size={20}
                      />
                    ) : null}
                  </View>

                  <View style={styles.actionRow}>
                    <InlineAction
                      icon="create-outline"
                      label="Edit"
                      onPress={() =>
                        navigation.navigate('SavedAddressEditor', {
                          mode: 'edit',
                          addressId: address.id,
                        })
                      }
                      styles={styles}
                    />
                    <InlineAction
                      icon="trash-outline"
                      label="Delete"
                      onPress={() => confirmDelete(address)}
                      styles={styles}
                      destructive
                    />
                    {!address.is_default ? (
                      <InlineAction
                        disabled={busy}
                        icon="star-outline"
                        label={busy ? 'Updating...' : 'Set default'}
                        onPress={() => {
                          void setDefault(address);
                        }}
                        styles={styles}
                      />
                    ) : null}
                  </View>
                </View>
              );
            })}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function InlineAction({
  icon,
  label,
  onPress,
  styles,
  destructive,
  disabled,
}: {
  icon: string;
  label: string;
  onPress: () => void;
  styles: ReturnType<typeof createStyles>;
  destructive?: boolean;
  disabled?: boolean;
}) {
  const theme = useTheme();
  return (
    <Pressable
      disabled={disabled}
      onPress={onPress}
      style={[
        styles.actionPill,
        destructive ? styles.actionPillDanger : null,
        disabled ? styles.actionPillDisabled : null,
      ]}
    >
      <Icon
        color={destructive ? theme.colors.deepRed : theme.colors.text}
        name={icon}
        size={15}
      />
      <Text
        style={[
          styles.actionText,
          destructive ? styles.actionTextDanger : null,
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: { flex: 1, backgroundColor: theme.colors.background },
    content: {
      padding: theme.spacing.screen,
      paddingTop: theme.spacing.stackTop,
      paddingBottom: 120,
      gap: 16,
    },
    hero: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    heroCopy: { flex: 1, gap: 6 },
    heading: { color: theme.colors.text, fontSize: 24, fontWeight: '800' },
    helper: { color: theme.colors.secondaryText, lineHeight: 20 },
    heroButton: {
      minHeight: 44,
      paddingHorizontal: 14,
      borderRadius: 16,
      backgroundColor: theme.colors.primary,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    heroButtonText: { color: theme.colors.onPrimary, fontWeight: '800' },
    loadingCard: {
      minHeight: 180,
      borderRadius: 26,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      alignItems: 'center',
      justifyContent: 'center',
      gap: 12,
    },
    loadingText: { color: theme.colors.secondaryText },
    emptyState: {
      borderRadius: 28,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      alignItems: 'center',
      paddingHorizontal: 20,
      paddingVertical: 28,
      gap: 12,
    },
    emptyIcon: {
      width: 56,
      height: 56,
      borderRadius: 28,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    emptyTitle: { color: theme.colors.text, fontSize: 18, fontWeight: '800' },
    emptyText: {
      color: theme.colors.secondaryText,
      textAlign: 'center',
      lineHeight: 20,
    },
    primaryAction: {
      marginTop: 6,
      minHeight: 46,
      borderRadius: 16,
      backgroundColor: theme.colors.primary,
      paddingHorizontal: 16,
      alignItems: 'center',
      justifyContent: 'center',
    },
    primaryActionText: {
      color: theme.colors.onPrimary,
      fontWeight: '800',
    },
    list: { gap: 14 },
    addressCard: {
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 16,
      gap: 14,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.08,
      shadowRadius: 18,
      shadowOffset: { width: 0, height: 8 },
      elevation: 3,
    },
    addressCardDefault: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.surface,
    },
    addressCardSelected: {
      shadowOpacity: 0.16,
    },
    cardHeader: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 10,
    },
    cardHeaderLeft: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 12,
    },
    iconShell: {
      width: 42,
      height: 42,
      borderRadius: 21,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    cardTitleWrap: { flex: 1, gap: 4 },
    badgeRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
    cardTitle: { color: theme.colors.text, fontSize: 16, fontWeight: '800' },
    defaultBadge: {
      borderRadius: 999,
      backgroundColor: theme.colors.successSoft,
      paddingHorizontal: 10,
      paddingVertical: 4,
    },
    defaultBadgeText: {
      color: theme.colors.success,
      fontSize: 11,
      fontWeight: '800',
      textTransform: 'uppercase',
    },
    cardAddress: { color: theme.colors.text, lineHeight: 20 },
    cardMeta: { color: theme.colors.secondaryText, lineHeight: 18 },
    actionRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 10,
    },
    actionPill: {
      minHeight: 38,
      borderRadius: 14,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surface,
      paddingHorizontal: 12,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    actionPillDanger: {
      backgroundColor: theme.colors.dangerSoft,
      borderColor: theme.colors.dangerSoft,
    },
    actionPillDisabled: {
      opacity: 0.6,
    },
    actionText: { color: theme.colors.text, fontWeight: '700' },
    actionTextDanger: { color: theme.colors.deepRed },
  });
