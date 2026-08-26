import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Ionicons';
import { ApiError, api } from '@services/api';
import { locationService } from '@services/location';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import {
  useAppActions,
  useSelectedLocation,
  useSession,
} from '@hooks/useAppStore';
import type { SavedAddress, SelectedLocation } from '@/types/app';
import type { LocationSearchResult } from '@/data/mockLocations';
import {
  buildSavedAddressSubtitle,
  mapSavedAddressToSelectedLocation,
  savedAddressLabelCopy,
} from '@screens/profile/savedAddresses/addressUtils';

export function LocationSelectScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation();
  const { user, token } = useSession();
  const selectedLocation = useSelectedLocation();
  const { pushToast, setSelectedLocation } = useAppActions();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<LocationSearchResult[]>([]);
  const [loadingSearch, setLoadingSearch] = useState(true);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [gpsLoading, setGpsLoading] = useState(false);
  const [savedAddresses, setSavedAddresses] = useState<SavedAddress[]>([]);

  useEffect(() => {
    const timer = setTimeout(() => {
      void runSearch(query);
    }, 260);

    return () => {
      clearTimeout(timer);
    };
  }, [query]);

  async function runSearch(nextQuery: string) {
    setLoadingSearch(true);
    setSearchError(null);

    try {
      const rows = await locationService.searchLocations(nextQuery);
      setResults(rows);
    } catch (error) {
      setSearchError(
        error instanceof Error
          ? error.message
          : 'Unable to load locations right now.',
      );
    } finally {
      setLoadingSearch(false);
    }
  }

  async function handleUseCurrentLocation() {
    setGpsLoading(true);
    setSearchError(null);

    try {
      const location = await locationService.getCurrentLocation();
      handleSelectLocation(location);
    } catch (error) {
      const description =
        error instanceof Error
          ? error.message
          : 'Unable to access your location right now.';
      setSearchError(description);
      pushToast('Location unavailable', description, 'error');
    } finally {
      setGpsLoading(false);
    }
  }

  useEffect(() => {
    if (!token) {
      setSavedAddresses([]);
      return;
    }

    let active = true;
    void api
      .getSavedAddresses(token)
      .then(rows => {
        if (active) {
          setSavedAddresses(rows);
        }
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const description =
          error instanceof ApiError
            ? error.message
            : 'Unable to load your saved addresses right now.';
        setSearchError(description);
      });

    return () => {
      active = false;
    };
  }, [token]);

  function handleSelectLocation(location: SelectedLocation) {
    setSelectedLocation(location);
    pushToast(
      'Location updated',
      `Delivering around ${location.city}.`,
      'success',
    );
    navigation.goBack();
  }

  const savedLocations = useMemo(() => {
    const locations: Array<{
      id: string;
      label: string;
      icon: string;
      location: SelectedLocation;
      subtitle?: string;
      isDefault?: boolean;
    }> = [];

    for (const address of savedAddresses) {
      locations.push({
        id: address.id,
        label: savedAddressLabelCopy[address.label],
        icon:
          address.label === 'HOME'
            ? 'home-outline'
            : address.label === 'WORK'
            ? 'briefcase-outline'
            : 'pin-outline',
        location: mapSavedAddressToSelectedLocation(address),
        subtitle: buildSavedAddressSubtitle(address),
        isDefault: address.is_default,
      });
    }

    if (
      selectedLocation &&
      !selectedLocation.savedAddressId &&
      selectedLocation.address !== user?.default_address
    ) {
      locations.push({
        id: 'saved-current',
        label: 'Recent',
        icon: 'time-outline',
        location: selectedLocation,
      });
    }

    return locations;
  }, [savedAddresses, selectedLocation, user?.default_address]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.keyboardWrap}
      >
        <View style={styles.header}>
          <View>
            <Text style={styles.title}>Select Location</Text>
            <Text style={styles.subtitle}>
              Search an area or pick your current spot.
            </Text>
          </View>
          <Pressable
            accessibilityRole="button"
            onPress={() => navigation.goBack()}
            style={styles.closeButton}
          >
            <Icon color={theme.colors.text} name="close" size={20} />
          </Pressable>
        </View>

        <View style={styles.searchShell}>
          <Icon color={theme.colors.hint} name="search-outline" size={18} />
          <TextInput
            autoCorrect={false}
            onChangeText={setQuery}
            placeholder="Search for area, street name..."
            placeholderTextColor={theme.colors.hint}
            style={styles.searchInput}
            value={query}
          />
          {query.length > 0 ? (
            <Pressable onPress={() => setQuery('')} style={styles.clearButton}>
              <Icon color={theme.colors.hint} name="close-circle" size={18} />
            </Pressable>
          ) : null}
        </View>

        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <Pressable
            disabled={gpsLoading}
            onPress={handleUseCurrentLocation}
            style={({ pressed }) => [
              styles.currentLocationCard,
              pressed ? styles.cardPressed : null,
              gpsLoading ? styles.cardDisabled : null,
            ]}
          >
            <View style={styles.currentLocationIcon}>
              {gpsLoading ? (
                <ActivityIndicator color={theme.colors.primary} size="small" />
              ) : (
                <Icon color={theme.colors.primary} name="locate" size={20} />
              )}
            </View>
            <View style={styles.currentLocationCopy}>
              <Text style={styles.currentLocationTitle}>
                Use Current Location
              </Text>
              <Text style={styles.currentLocationText}>
                Let us find restaurants around you automatically.
              </Text>
            </View>
          </Pressable>

          {savedLocations.length > 0 ? (
            <View style={styles.section}>
              <View style={styles.resultsHeader}>
                <Text style={styles.sectionTitle}>Saved locations</Text>
                <Pressable
                  onPress={() => navigation.navigate('SavedAddresses' as never)}
                >
                  <Text style={styles.manageText}>Manage</Text>
                </Pressable>
              </View>
              <View style={styles.savedList}>
                {savedLocations.map(item => {
                  const active = selectedLocation?.savedAddressId
                    ? selectedLocation.savedAddressId ===
                      item.location.savedAddressId
                    : selectedLocation?.address === item.location.address;
                  return (
                    <Pressable
                      key={item.id}
                      onPress={() => handleSelectLocation(item.location)}
                      style={[
                        styles.savedItem,
                        active ? styles.savedItemActive : null,
                      ]}
                    >
                      <View style={styles.savedIcon}>
                        <Icon
                          color={theme.colors.primary}
                          name={item.icon}
                          size={18}
                        />
                      </View>
                      <View style={styles.savedCopy}>
                        <View style={styles.savedLabelRow}>
                          <Text style={styles.savedLabel}>{item.label}</Text>
                          {item.isDefault ? (
                            <View style={styles.savedBadge}>
                              <Text style={styles.savedBadgeText}>Default</Text>
                            </View>
                          ) : null}
                        </View>
                        <Text numberOfLines={2} style={styles.savedAddress}>
                          {item.location.address}
                        </Text>
                        {item.subtitle ? (
                          <Text numberOfLines={1} style={styles.savedMeta}>
                            {item.subtitle}
                          </Text>
                        ) : null}
                      </View>
                      {active ? (
                        <Icon
                          color={theme.colors.primary}
                          name="checkmark-circle"
                          size={20}
                        />
                      ) : null}
                    </Pressable>
                  );
                })}
              </View>
            </View>
          ) : null}

          <View style={styles.section}>
            <View style={styles.resultsHeader}>
              <Text style={styles.sectionTitle}>Search results</Text>
              {loadingSearch ? (
                <Text style={styles.helperText}>Searching…</Text>
              ) : (
                <Text style={styles.helperText}>{results.length} found</Text>
              )}
            </View>

            {searchError ? (
              <View style={styles.feedbackCard}>
                <Text style={styles.feedbackTitle}>
                  Couldn’t load locations
                </Text>
                <Text style={styles.feedbackText}>{searchError}</Text>
                <Pressable
                  onPress={() => void runSearch(query)}
                  style={styles.retryButton}
                >
                  <Text style={styles.retryButtonText}>Retry</Text>
                </Pressable>
              </View>
            ) : loadingSearch ? (
              <View style={styles.resultsList}>
                {Array.from({ length: 4 }).map((_, index) => (
                  <View key={index} style={styles.skeletonItem}>
                    <View style={styles.skeletonIcon} />
                    <View style={styles.skeletonCopy}>
                      <View style={styles.skeletonTitle} />
                      <View style={styles.skeletonSubtitle} />
                    </View>
                  </View>
                ))}
              </View>
            ) : results.length > 0 ? (
              <View style={styles.resultsList}>
                {results.map(item => {
                  const active = selectedLocation?.address === item.address;
                  return (
                    <Pressable
                      key={item.id}
                      onPress={() => handleSelectLocation(item)}
                      style={[
                        styles.resultItem,
                        active ? styles.resultItemActive : null,
                      ]}
                    >
                      <View style={styles.resultIcon}>
                        <Icon
                          color={theme.colors.primary}
                          name="location-outline"
                          size={18}
                        />
                      </View>
                      <View style={styles.resultCopy}>
                        <Text style={styles.resultTitle}>{item.title}</Text>
                        <Text numberOfLines={2} style={styles.resultSubtitle}>
                          {item.subtitle}
                        </Text>
                      </View>
                      {active ? (
                        <Icon
                          color={theme.colors.primary}
                          name="checkmark-circle"
                          size={20}
                        />
                      ) : (
                        <Icon
                          color={theme.colors.hint}
                          name="chevron-forward"
                          size={18}
                        />
                      )}
                    </Pressable>
                  );
                })}
              </View>
            ) : (
              <View style={styles.feedbackCard}>
                <Text style={styles.feedbackTitle}>No matching locations</Text>
                <Text style={styles.feedbackText}>
                  Try a nearby area, landmark, or street name instead.
                </Text>
              </View>
            )}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    keyboardWrap: {
      flex: 1,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 8,
      paddingBottom: 14,
      gap: 16,
    },
    title: {
      color: theme.colors.text,
      fontSize: 24,
      fontWeight: '800',
    },
    subtitle: {
      marginTop: 4,
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 20,
    },
    closeButton: {
      width: 40,
      height: 40,
      borderRadius: 20,
      backgroundColor: theme.colors.card,
      alignItems: 'center',
      justifyContent: 'center',
    },
    searchShell: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      marginHorizontal: theme.spacing.screen,
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      paddingHorizontal: 16,
      paddingVertical: 14,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.06,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 2,
    },
    searchInput: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 15,
      padding: 0,
    },
    clearButton: {
      marginLeft: 'auto',
    },
    content: {
      padding: theme.spacing.screen,
      paddingTop: 14,
      paddingBottom: 44,
      gap: 18,
    },
    currentLocationCard: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 14,
      borderRadius: 20,
      backgroundColor: theme.colors.surfaceAlt,
      padding: 16,
    },
    cardPressed: {
      opacity: 0.92,
    },
    cardDisabled: {
      opacity: 0.8,
    },
    currentLocationIcon: {
      width: 44,
      height: 44,
      borderRadius: 22,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
    },
    currentLocationCopy: {
      flex: 1,
      gap: 2,
    },
    currentLocationTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    currentLocationText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 18,
    },
    section: {
      gap: 12,
    },
    sectionTitle: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    helperText: {
      color: theme.colors.hint,
      fontSize: 12,
      fontWeight: '600',
    },
    savedList: {
      gap: 10,
    },
    savedItem: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 14,
    },
    savedItemActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    savedIcon: {
      width: 38,
      height: 38,
      borderRadius: 19,
      backgroundColor: theme.colors.surfaceAlt,
      alignItems: 'center',
      justifyContent: 'center',
    },
    savedCopy: {
      flex: 1,
      gap: 3,
    },
    savedLabel: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    savedLabelRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    savedAddress: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    savedMeta: {
      color: theme.colors.hint,
      fontSize: 11,
      lineHeight: 16,
    },
    savedBadge: {
      borderRadius: 999,
      backgroundColor: theme.colors.successSoft,
      paddingHorizontal: 8,
      paddingVertical: 3,
    },
    savedBadgeText: {
      color: theme.colors.success,
      fontSize: 10,
      fontWeight: '800',
      textTransform: 'uppercase',
    },
    manageText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    resultsHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    resultsList: {
      gap: 10,
    },
    resultItem: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 14,
    },
    resultItemActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    resultIcon: {
      width: 40,
      height: 40,
      borderRadius: 20,
      backgroundColor: theme.colors.surfaceAlt,
      alignItems: 'center',
      justifyContent: 'center',
    },
    resultCopy: {
      flex: 1,
      gap: 3,
    },
    resultTitle: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    resultSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    feedbackCard: {
      borderRadius: 18,
      backgroundColor: theme.colors.card,
      padding: 16,
      gap: 8,
      alignItems: 'flex-start',
    },
    feedbackTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    feedbackText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      lineHeight: 20,
    },
    retryButton: {
      marginTop: 2,
      borderRadius: 999,
      backgroundColor: theme.colors.primary,
      paddingHorizontal: 14,
      paddingVertical: 9,
    },
    retryButtonText: {
      color: theme.colors.white,
      fontSize: 13,
      fontWeight: '800',
    },
    skeletonItem: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      borderRadius: 18,
      backgroundColor: theme.colors.card,
      padding: 14,
    },
    skeletonIcon: {
      width: 40,
      height: 40,
      borderRadius: 20,
      backgroundColor: theme.colors.border,
    },
    skeletonCopy: {
      flex: 1,
      gap: 8,
    },
    skeletonTitle: {
      width: '42%',
      height: 12,
      borderRadius: 999,
      backgroundColor: theme.colors.border,
    },
    skeletonSubtitle: {
      width: '70%',
      height: 10,
      borderRadius: 999,
      backgroundColor: theme.colors.divider,
    },
  });
