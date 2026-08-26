import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActivityIndicator,
  Animated,
  Easing,
  FlatList,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  useWindowDimensions,
  type ListRenderItem,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Ionicons';
import { useAppForegroundEffect } from '@hooks/useAppForegroundEffect';
import { api } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type {
  FulfillmentSelection,
  LocationScheduleDayGroup,
  LocationScheduleOption,
  LocationScheduleOptionsResponse,
  OrderFulfillmentType,
  RestaurantLocation,
} from '@/types/app';
import {
  formatFulfillmentSelectionLabel,
  getScheduledSlotInvalidMessage,
  getFulfillmentEtaLabel,
  getFulfillmentUnavailableReason,
  isScheduledSlotPresent,
  isFulfillmentEnabled,
} from '@utils/fulfillment';

interface FulfillmentSelectionSheetProps {
  visible: boolean;
  restaurantId: string;
  location: RestaurantLocation | null;
  token?: string | null;
  initialSelection?: FulfillmentSelection | null;
  canDismiss?: boolean;
  onDismiss: () => void;
  onConfirm: (selection: FulfillmentSelection) => void;
}

type Step = 'FULFILLMENT' | 'TIMING' | 'SCHEDULE';

const fulfillmentChoices: Array<{
  type: OrderFulfillmentType;
  title: string;
  icon: string;
}> = [
  { type: 'DELIVERY', title: 'Delivery', icon: 'bicycle-outline' },
  { type: 'PICKUP', title: 'Pickup', icon: 'bag-handle-outline' },
];

function toThirtyMinuteDisplaySlots(
  groups: LocationScheduleDayGroup[],
): LocationScheduleDayGroup[] {
  return groups
    .map(group => {
      const filtered: LocationScheduleOption[] = [];
      let lastAcceptedAt: number | null = null;

      for (const slot of group.slots) {
        const timestamp = new Date(slot.scheduled_at).getTime();
        if (Number.isNaN(timestamp)) {
          continue;
        }
        if (
          lastAcceptedAt === null ||
          timestamp - lastAcceptedAt >= 30 * 60 * 1000
        ) {
          filtered.push(slot);
          lastAcceptedAt = timestamp;
        }
      }

      return {
        ...group,
        slots: filtered,
      };
    })
    .filter(group => group.slots.length > 0);
}

export function FulfillmentSelectionSheet({
  visible,
  restaurantId,
  location,
  token,
  initialSelection,
  canDismiss = true,
  onDismiss,
  onConfirm,
}: FulfillmentSelectionSheetProps): React.JSX.Element | null {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const insets = useSafeAreaInsets();
  const { width } = useWindowDimensions();
  const [mounted, setMounted] = useState(visible);
  const [step, setStep] = useState<Step>('FULFILLMENT');
  const [selectedFulfillment, setSelectedFulfillment] =
    useState<OrderFulfillmentType>(
      initialSelection?.fulfillmentType ?? 'DELIVERY',
    );
  const [selectedSchedule, setSelectedSchedule] =
    useState<FulfillmentSelection | null>(initialSelection ?? null);
  const [scheduleOptions, setScheduleOptions] =
    useState<LocationScheduleOptionsResponse | null>(null);
  const [scheduleOptionsKey, setScheduleOptionsKey] = useState<string | null>(
    null,
  );
  const [selectedScheduleDate, setSelectedScheduleDate] = useState<
    string | null
  >(null);
  const [scheduleLoading, setScheduleLoading] = useState(false);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const backdrop = useRef(new Animated.Value(visible ? 1 : 0)).current;
  const sheet = useRef(new Animated.Value(visible ? 1 : 0)).current;
  const lastScheduleRefreshAtRef = useRef(0);
  const scheduleOptionsRef = useRef<LocationScheduleOptionsResponse | null>(
    null,
  );
  const scheduleOptionsSignatureRef = useRef<string | null>(null);
  const scheduleFetchPromiseRef =
    useRef<Promise<LocationScheduleOptionsResponse | null> | null>(null);
  const scheduleFetchKeyRef = useRef<string | null>(null);
  const latestScheduleRequestIdRef = useRef(0);

  useEffect(() => {
    if (visible) {
      setMounted(true);
      setStep(initialSelection ? 'TIMING' : 'FULFILLMENT');
      setSelectedFulfillment(initialSelection?.fulfillmentType ?? 'DELIVERY');
      setSelectedSchedule(initialSelection ?? null);
      setSelectedScheduleDate(
        initialSelection?.scheduledAt
          ? initialSelection.scheduledAt.slice(0, 10)
          : null,
      );
      setScheduleError(null);
      Animated.parallel([
        Animated.timing(backdrop, {
          toValue: 1,
          duration: 220,
          easing: Easing.out(Easing.cubic),
          useNativeDriver: true,
        }),
        Animated.spring(sheet, {
          toValue: 1,
          damping: 18,
          stiffness: 180,
          mass: 0.9,
          useNativeDriver: true,
        }),
      ]).start();
      return;
    }

    Animated.parallel([
      Animated.timing(backdrop, {
        toValue: 0,
        duration: 180,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }),
      Animated.timing(sheet, {
        toValue: 0,
        duration: 180,
        easing: Easing.in(Easing.cubic),
        useNativeDriver: true,
      }),
    ]).start(({ finished }) => {
      if (finished) {
        setMounted(false);
      }
    });
  }, [backdrop, initialSelection, sheet, visible]);

  const selectedScheduledDateKey =
    selectedSchedule?.scheduleType === 'SCHEDULED' &&
    selectedSchedule.scheduledAt
      ? selectedSchedule.scheduledAt.slice(0, 10)
      : null;
  const scheduleRequestKey = useMemo(
    () =>
      location ? `${restaurantId}:${location.id}:${selectedFulfillment}` : null,
    [location, restaurantId, selectedFulfillment],
  );
  const activeScheduleOptions = useMemo(
    () => (scheduleOptionsKey === scheduleRequestKey ? scheduleOptions : null),
    [scheduleOptions, scheduleOptionsKey, scheduleRequestKey],
  );

  const applyScheduleOptionsState = React.useCallback(
    (
      key: string,
      response: LocationScheduleOptionsResponse | null,
      fallbackDate: string | null,
      nextError: string | null,
    ) => {
      if (response) {
        const signature = JSON.stringify(response);
        const previousSignature = scheduleOptionsSignatureRef.current;
        scheduleOptionsRef.current = response;
        scheduleOptionsSignatureRef.current = signature;
        setScheduleOptions(previous =>
          previousSignature === signature ? previous : response,
        );
        setScheduleOptionsKey(previous => (previous === key ? previous : key));
      } else {
        scheduleOptionsRef.current = null;
        scheduleOptionsSignatureRef.current = null;
        setScheduleOptions(previous => (previous === null ? previous : null));
        setScheduleOptionsKey(previous =>
          previous === null ? previous : null,
        );
      }

      setScheduleError(previous =>
        previous === nextError ? previous : nextError,
      );
      setSelectedScheduleDate(previous => {
        const nextDate = fallbackDate;
        return previous === nextDate ? previous : nextDate;
      });
    },
    [],
  );

  const refreshScheduleOptions = React.useCallback(
    async ({
      force = false,
      showLoader = false,
    }: {
      force?: boolean;
      showLoader?: boolean;
    } = {}): Promise<LocationScheduleOptionsResponse | null> => {
      if (!visible || !location || !scheduleRequestKey) {
        return null;
      }
      if (
        scheduleFetchPromiseRef.current &&
        scheduleFetchKeyRef.current === scheduleRequestKey
      ) {
        if (showLoader) {
          setScheduleLoading(true);
          return scheduleFetchPromiseRef.current.finally(() => {
            setScheduleLoading(false);
          });
        }
        return scheduleFetchPromiseRef.current;
      }
      const now = Date.now();
      if (
        !force &&
        scheduleOptionsRef.current &&
        scheduleOptionsKey === scheduleRequestKey &&
        now - lastScheduleRefreshAtRef.current < 10000
      ) {
        return scheduleOptionsRef.current;
      }

      const requestId = latestScheduleRequestIdRef.current + 1;
      latestScheduleRequestIdRef.current = requestId;
      lastScheduleRefreshAtRef.current = now;
      if (showLoader) {
        setScheduleLoading(previous => (previous ? previous : true));
      }
      const request =
        (async (): Promise<LocationScheduleOptionsResponse | null> => {
          try {
            const response = await api.getRestaurantLocationScheduleOptions(
              restaurantId,
              location.id,
              selectedFulfillment,
              token,
            );
            if (latestScheduleRequestIdRef.current !== requestId) {
              return response;
            }
            const matchingGroup = selectedScheduledDateKey
              ? response.groups.find(
                  group => group.date === selectedScheduledDateKey,
                )
              : undefined;
            applyScheduleOptionsState(
              scheduleRequestKey,
              response,
              matchingGroup?.date ?? response.groups[0]?.date ?? null,
              null,
            );
            return response;
          } catch (error) {
            if (latestScheduleRequestIdRef.current !== requestId) {
              return null;
            }
            applyScheduleOptionsState(
              scheduleRequestKey,
              null,
              null,
              error instanceof Error
                ? error.message
                : 'Could not load slots. Retry.',
            );
            return null;
          } finally {
            if (showLoader) {
              setScheduleLoading(false);
            }
            if (scheduleFetchKeyRef.current === scheduleRequestKey) {
              scheduleFetchPromiseRef.current = null;
              scheduleFetchKeyRef.current = null;
            }
          }
        })();
      scheduleFetchPromiseRef.current = request;
      scheduleFetchKeyRef.current = scheduleRequestKey;
      return request;
    },
    [
      applyScheduleOptionsState,
      location,
      restaurantId,
      scheduleOptionsKey,
      scheduleRequestKey,
      selectedFulfillment,
      selectedScheduledDateKey,
      token,
      visible,
    ],
  );

  useEffect(() => {
    if (!visible || !scheduleRequestKey) {
      return;
    }
    refreshScheduleOptions().catch(() => undefined);
  }, [refreshScheduleOptions, scheduleRequestKey, visible]);

  useEffect(() => {
    if (!visible || step !== 'SCHEDULE') {
      return;
    }
    refreshScheduleOptions({
      showLoader: activeScheduleOptions == null,
    }).catch(() => undefined);
  }, [activeScheduleOptions, refreshScheduleOptions, step, visible]);

  useAppForegroundEffect(() => {
    refreshScheduleOptions({
      force: true,
      showLoader: step === 'SCHEDULE' && activeScheduleOptions == null,
    }).catch(() => undefined);
  }, visible);

  const handleDismiss = () => {
    if (!canDismiss) {
      return;
    }
    onDismiss();
  };

  const sheetStyle = useMemo(
    () => ({
      opacity: sheet,
      transform: [
        {
          translateY: sheet.interpolate({
            inputRange: [0, 1],
            outputRange: [32, 0],
          }),
        },
      ],
    }),
    [sheet],
  );
  const sheetInsetStyle = useMemo(
    () => ({
      paddingBottom: Math.max(insets.bottom, 12) + 4,
    }),
    [insets.bottom],
  );

  const handleBack = () => {
    if (step === 'SCHEDULE') {
      setStep('TIMING');
      return;
    }
    if (step === 'TIMING') {
      setStep('FULFILLMENT');
    }
  };

  const headerTitle =
    step === 'FULFILLMENT'
      ? 'How would you like your order?'
      : step === 'TIMING'
      ? 'When do you want your order?'
      : 'Choose a time slot';

  const headerSubtitle =
    step === 'FULFILLMENT'
      ? 'Pick the best way to receive this order.'
      : step === 'TIMING'
      ? 'ASAP gets the kitchen moving right away.'
      : 'Only valid branch slots are shown here.';

  const currentSelectionLabel = formatFulfillmentSelectionLabel(location, {
    fulfillmentType: selectedFulfillment,
    scheduleType: selectedSchedule?.scheduleType ?? 'ASAP',
    scheduledAt: selectedSchedule?.scheduledAt ?? null,
  });
  const asapAvailable = activeScheduleOptions?.asap_available ?? true;
  const asapUnavailableReason =
    activeScheduleOptions?.asap_unavailable_reason ??
    'ASAP ordering is unavailable right now.';
  const displayScheduleGroups = useMemo(
    () => toThirtyMinuteDisplaySlots(activeScheduleOptions?.groups ?? []),
    [activeScheduleOptions?.groups],
  );
  const activeDisplayScheduleGroup = useMemo(
    () =>
      displayScheduleGroups.find(
        group => group.date === selectedScheduleDate,
      ) ??
      displayScheduleGroups[0] ??
      null,
    [displayScheduleGroups, selectedScheduleDate],
  );
  // Hoisted out of the JSX so the date rail is not rebuilt on every render of
  // the sheet.
  const renderScheduleDate = useCallback<
    ListRenderItem<(typeof displayScheduleGroups)[number]>
  >(
    ({ item }) => {
      const isActive = item.date === activeDisplayScheduleGroup?.date;
      return (
        <Pressable
          onPress={() => setSelectedScheduleDate(item.date)}
          style={[styles.dateChip, isActive && styles.dateChipActive]}
        >
          <Text
            style={[styles.dateChipText, isActive && styles.dateChipTextActive]}
          >
            {item.label}
          </Text>
        </Pressable>
      );
    },
    [activeDisplayScheduleGroup?.date, styles],
  );

  const slotColumns = 3;
  const slotButtonWidth = useMemo(() => {
    const horizontalPadding = 40;
    const interItemGap = 16;
    const availableWidth = width - horizontalPadding - interItemGap;
    return Math.floor(availableWidth / slotColumns);
  }, [slotColumns, width]);

  if (!mounted) {
    return null;
  }

  return (
    <Modal
      animationType="none"
      onRequestClose={handleDismiss}
      transparent
      visible={mounted}
    >
      <View style={styles.root}>
        <Pressable onPress={handleDismiss} style={StyleSheet.absoluteFill}>
          <Animated.View style={[styles.backdrop, { opacity: backdrop }]} />
        </Pressable>
        <Animated.View style={[styles.sheet, sheetStyle, sheetInsetStyle]}>
          <View style={styles.handle} />
          <View style={styles.header}>
            <View style={styles.headerLeading}>
              {step !== 'FULFILLMENT' ? (
                <Pressable onPress={handleBack} style={styles.backButton}>
                  <Icon color={theme.colors.text} name="arrow-back" size={18} />
                </Pressable>
              ) : null}
            </View>
            <View style={styles.headerCopy}>
              <Text style={styles.title}>{headerTitle}</Text>
              <Text style={styles.subtitle}>{headerSubtitle}</Text>
            </View>
            {canDismiss ? (
              <Pressable onPress={handleDismiss} style={styles.closeButton}>
                <Icon color={theme.colors.text} name="close" size={18} />
              </Pressable>
            ) : null}
          </View>

          {selectedSchedule ? (
            <View style={styles.summaryPill}>
              <Icon
                color={theme.colors.primary}
                name="sparkles-outline"
                size={14}
              />
              <Text style={styles.summaryPillText}>
                {currentSelectionLabel}
              </Text>
            </View>
          ) : null}

          {step === 'FULFILLMENT' ? (
            <View style={styles.choiceColumn}>
              {fulfillmentChoices.map(choice => {
                const enabled = isFulfillmentEnabled(location, choice.type);
                const eta = getFulfillmentEtaLabel(location, choice.type);
                const reason = !enabled
                  ? getFulfillmentUnavailableReason(location, choice.type)
                  : null;

                return (
                  <Pressable
                    key={choice.type}
                    disabled={!enabled}
                    onPress={() => {
                      setSelectedFulfillment(choice.type);
                      setSelectedSchedule(current =>
                        current
                          ? {
                              ...current,
                              fulfillmentType: choice.type,
                            }
                          : null,
                      );
                      setStep('TIMING');
                    }}
                    style={[
                      styles.choiceCard,
                      !enabled && styles.choiceCardDisabled,
                    ]}
                  >
                    <View style={styles.choiceIcon}>
                      <Icon
                        color={theme.colors.primary}
                        name={choice.icon}
                        size={18}
                      />
                    </View>
                    <View style={styles.choiceCopy}>
                      <Text style={styles.choiceTitle}>{choice.title}</Text>
                      <Text style={styles.choiceMeta}>
                        {enabled
                          ? `${eta} • ${
                              choice.type === 'DELIVERY'
                                ? 'Delivered to you'
                                : 'Ready for pickup'
                            }`
                          : reason ?? 'Unavailable right now'}
                      </Text>
                    </View>
                    <Icon
                      color={theme.colors.hint}
                      name="chevron-forward"
                      size={18}
                    />
                  </Pressable>
                );
              })}
            </View>
          ) : null}

          {step === 'TIMING' ? (
            <View style={styles.choiceColumn}>
              <Pressable
                disabled={!asapAvailable}
                onPress={() => {
                  refreshScheduleOptions({ force: true })
                    .then(response => {
                      if (response && !response.asap_available) {
                        setScheduleError(
                          response.asap_unavailable_reason ??
                            'ASAP ordering is unavailable right now.',
                        );
                        return;
                      }
                      onConfirm({
                        fulfillmentType: selectedFulfillment,
                        scheduleType: 'ASAP',
                        scheduledAt: new Date().toISOString(),
                      });
                    })
                    .catch(() => undefined);
                }}
                style={[
                  styles.choiceCard,
                  !asapAvailable && styles.choiceCardDisabled,
                ]}
              >
                <View style={styles.choiceIcon}>
                  <Icon
                    color={theme.colors.primary}
                    name="flash-outline"
                    size={18}
                  />
                </View>
                <View style={styles.choiceCopy}>
                  <Text style={styles.choiceTitle}>ASAP</Text>
                  <Text style={styles.choiceMeta}>
                    {asapAvailable
                      ? `${getFulfillmentEtaLabel(
                          location,
                          selectedFulfillment,
                        )} • Start right away`
                      : asapUnavailableReason}
                  </Text>
                </View>
                <Icon
                  color={theme.colors.hint}
                  name="chevron-forward"
                  size={18}
                />
              </Pressable>

              <Pressable
                disabled={!location?.future_order_enabled}
                onPress={() => setStep('SCHEDULE')}
                style={[
                  styles.choiceCard,
                  !location?.future_order_enabled && styles.choiceCardDisabled,
                ]}
              >
                <View style={styles.choiceIcon}>
                  <Icon
                    color={theme.colors.primary}
                    name="calendar-outline"
                    size={18}
                  />
                </View>
                <View style={styles.choiceCopy}>
                  <Text style={styles.choiceTitle}>Schedule for later</Text>
                  <Text style={styles.choiceMeta}>
                    {location?.future_order_enabled
                      ? `Choose a future ${
                          selectedFulfillment === 'DELIVERY'
                            ? 'delivery'
                            : 'pickup'
                        } slot`
                      : 'Future ordering is disabled for this branch'}
                  </Text>
                </View>
                <Icon
                  color={theme.colors.hint}
                  name="chevron-forward"
                  size={18}
                />
              </Pressable>
            </View>
          ) : null}

          {step === 'SCHEDULE' ? (
            <View style={styles.scheduleWrap}>
              {scheduleLoading ? (
                <View style={styles.loadingWrap}>
                  <ActivityIndicator color={theme.colors.primary} />
                  <Text style={styles.loadingText}>Loading valid slots…</Text>
                </View>
              ) : null}

              {!scheduleLoading && scheduleError ? (
                <View style={styles.messageCard}>
                  <Text style={styles.messageTitle}>Could not load slots.</Text>
                  <Text style={styles.messageText}>{scheduleError}</Text>
                  <Pressable
                    onPress={() => {
                      refreshScheduleOptions({
                        force: true,
                        showLoader: true,
                      }).catch(() => undefined);
                    }}
                    style={styles.messageAction}
                  >
                    <Text style={styles.messageActionText}>Retry</Text>
                  </Pressable>
                </View>
              ) : null}

              {!scheduleLoading &&
              !scheduleError &&
              activeScheduleOptions &&
              displayScheduleGroups.length > 0 ? (
                <View style={styles.schedulePicker}>
                  <View style={styles.dateRailWrap}>
                    <FlatList
                      data={displayScheduleGroups}
                      horizontal
                      keyExtractor={item => item.date}
                      showsHorizontalScrollIndicator={false}
                      contentContainerStyle={styles.dateRail}
                      renderItem={renderScheduleDate}
                    />
                  </View>

                  {activeDisplayScheduleGroup ? (
                    <View style={styles.groupBlock}>
                      <Text style={styles.groupTitle}>
                        {activeDisplayScheduleGroup.label}
                      </Text>
                      <ScrollView
                        contentContainerStyle={styles.scheduleContent}
                        nestedScrollEnabled
                        showsVerticalScrollIndicator={false}
                      >
                        <View style={styles.slotGrid}>
                          {activeDisplayScheduleGroup.slots.map(slot => {
                            const isSelected =
                              selectedSchedule?.scheduleType === 'SCHEDULED' &&
                              selectedSchedule.scheduledAt ===
                                slot.scheduled_at;
                            return (
                              <Pressable
                                key={slot.scheduled_at}
                                onPress={() => {
                                  refreshScheduleOptions({ force: true })
                                    .then(response => {
                                      if (!response) {
                                        return;
                                      }
                                      if (
                                        !isScheduledSlotPresent(
                                          response,
                                          slot.scheduled_at,
                                        )
                                      ) {
                                        setScheduleError(
                                          getScheduledSlotInvalidMessage(
                                            response,
                                          ),
                                        );
                                        return;
                                      }
                                      setSelectedSchedule({
                                        fulfillmentType: selectedFulfillment,
                                        scheduleType: 'SCHEDULED',
                                        scheduledAt: slot.scheduled_at,
                                      });
                                      onConfirm({
                                        fulfillmentType: selectedFulfillment,
                                        scheduleType: 'SCHEDULED',
                                        scheduledAt: slot.scheduled_at,
                                      });
                                    })
                                    .catch(() => undefined);
                                }}
                                style={[
                                  styles.slotButton,
                                  { width: slotButtonWidth },
                                  isSelected && styles.slotButtonActive,
                                ]}
                              >
                                <Text
                                  style={[
                                    styles.slotButtonText,
                                    isSelected && styles.slotButtonTextActive,
                                  ]}
                                >
                                  {slot.label}
                                </Text>
                              </Pressable>
                            );
                          })}
                        </View>
                      </ScrollView>
                    </View>
                  ) : null}
                </View>
              ) : null}

              {!scheduleLoading &&
              !scheduleError &&
              activeScheduleOptions &&
              displayScheduleGroups.length === 0 ? (
                <View style={styles.messageCard}>
                  <Text style={styles.messageTitle}>
                    No valid slots available
                  </Text>
                  <Text style={styles.messageText}>
                    {activeScheduleOptions.scheduled_unavailable_reason ??
                      'No valid slots available right now.'}
                  </Text>
                </View>
              ) : null}
            </View>
          ) : null}
        </Animated.View>
      </View>
    </Modal>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    root: {
      flex: 1,
      justifyContent: 'flex-end',
    },
    backdrop: {
      flex: 1,
      backgroundColor: theme.colors.overlay,
    },
    sheet: {
      backgroundColor: theme.colors.modalSurface,
      borderTopLeftRadius: 28,
      borderTopRightRadius: 28,
      paddingHorizontal: 20,
      paddingTop: 12,
      paddingBottom: 16,
      gap: 16,
      maxHeight: '78%',
    },
    handle: {
      alignSelf: 'center',
      width: 46,
      height: 5,
      borderRadius: 999,
      backgroundColor: theme.colors.border,
    },
    header: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    headerLeading: {
      width: 34,
      alignItems: 'flex-start',
      justifyContent: 'center',
    },
    headerCopy: {
      flex: 1,
      gap: 4,
    },
    backButton: {
      width: 34,
      height: 34,
      borderRadius: 17,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    title: {
      fontSize: 22,
      fontWeight: '800',
      color: theme.colors.text,
    },
    subtitle: {
      fontSize: 14,
      lineHeight: 20,
      color: theme.colors.hint,
    },
    closeButton: {
      width: 34,
      height: 34,
      borderRadius: 17,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    summaryPill: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      alignSelf: 'flex-start',
      paddingHorizontal: 12,
      paddingVertical: 8,
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
    },
    summaryPillText: {
      fontSize: 13,
      fontWeight: '700',
      color: theme.colors.text,
    },
    choiceColumn: {
      gap: 12,
    },
    choiceCard: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 14,
      paddingHorizontal: 16,
      paddingVertical: 16,
      borderRadius: 20,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
    },
    choiceCardDisabled: {
      opacity: 0.45,
    },
    choiceIcon: {
      width: 42,
      height: 42,
      borderRadius: 21,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primarySoft,
    },
    choiceCopy: {
      flex: 1,
      gap: 4,
    },
    choiceTitle: {
      fontSize: 16,
      fontWeight: '800',
      color: theme.colors.text,
    },
    choiceMeta: {
      fontSize: 13,
      lineHeight: 18,
      color: theme.colors.hint,
    },
    scheduleWrap: {
      gap: 14,
      minHeight: 320,
    },
    schedulePicker: {
      gap: 14,
      flex: 1,
    },
    dateRailWrap: {
      marginHorizontal: -2,
      paddingBottom: 2,
    },
    dateRail: {
      gap: 8,
      paddingHorizontal: 2,
    },
    dateChip: {
      minHeight: 36,
      paddingHorizontal: 14,
      borderRadius: 999,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.background,
      alignItems: 'center',
      justifyContent: 'center',
    },
    dateChipActive: {
      backgroundColor: theme.colors.primary,
      borderColor: theme.colors.primary,
    },
    dateChipText: {
      fontSize: 12,
      fontWeight: '700',
      color: theme.colors.text,
    },
    dateChipTextActive: {
      color: theme.colors.white,
    },
    loadingWrap: {
      paddingVertical: 20,
      alignItems: 'center',
      gap: 10,
    },
    loadingText: {
      fontSize: 13,
      color: theme.colors.hint,
    },
    messageCard: {
      padding: 16,
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      gap: 10,
    },
    messageTitle: {
      fontSize: 14,
      fontWeight: '800',
      color: theme.colors.text,
    },
    messageText: {
      fontSize: 14,
      lineHeight: 20,
      color: theme.colors.hint,
    },
    messageAction: {
      alignSelf: 'flex-start',
      minHeight: 34,
      paddingHorizontal: 14,
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    messageActionText: {
      fontSize: 12,
      fontWeight: '800',
      color: theme.colors.primary,
    },
    scheduleContent: {
      paddingBottom: 8,
    },
    groupBlock: {
      gap: 12,
      flex: 1,
    },
    groupTitle: {
      fontSize: 14,
      fontWeight: '800',
      color: theme.colors.text,
    },
    slotGrid: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
      alignItems: 'flex-start',
    },
    slotButton: {
      paddingHorizontal: 10,
      paddingVertical: 10,
      borderRadius: 12,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.background,
      alignItems: 'center',
    },
    slotButtonActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    slotButtonText: {
      fontSize: 11.5,
      fontWeight: '700',
      color: theme.colors.text,
    },
    slotButtonTextActive: {
      color: theme.colors.primary,
    },
  });

