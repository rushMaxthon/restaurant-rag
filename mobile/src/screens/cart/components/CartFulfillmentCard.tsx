import React from 'react';
import { Pressable, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { useTheme, useThemedStyles } from '@/theme';
import type { CartFulfillmentType, OrderScheduleType } from '@/types/app';
import { createStyles } from '../styles';

interface CartFulfillmentCardProps {
  fulfillmentType: CartFulfillmentType;
  scheduleType: OrderScheduleType;
  deliveryAddress: string;
  pickupAddress: string;
  fulfillmentChipLabel: string;
  timingLabel: string;
  timingSupportingLabel: string | null;
  activeFulfillmentAvailable: boolean;
  activeFulfillmentReason: string | null;
  deliveryEnabled: boolean;
  pickupEnabled: boolean;
  showMissingDeliveryAddressWarning: boolean;
  onFulfillmentModePress: (mode: 'DELIVERY' | 'PICKUP') => void;
  onOpenFulfillmentSheet: () => void;
  onChangeAddress: () => void;
}

/**
 * Delivery/pickup mode, address and timing summary.
 *
 * Split out of `CartScreen` so it re-renders only when the fulfillment
 * selection itself changes, not when the cart items or the notes field do.
 */
function CartFulfillmentCardComponent({
  fulfillmentType,
  scheduleType,
  deliveryAddress,
  pickupAddress,
  fulfillmentChipLabel,
  timingLabel,
  timingSupportingLabel,
  activeFulfillmentAvailable,
  activeFulfillmentReason,
  deliveryEnabled,
  pickupEnabled,
  showMissingDeliveryAddressWarning,
  onFulfillmentModePress,
  onOpenFulfillmentSheet,
  onChangeAddress,
}: CartFulfillmentCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.fulfillmentCard}>
      <View style={styles.fulfillmentHeader}>
        <View style={styles.fulfillmentHeaderCopy}>
          <Text style={styles.fulfillmentTitle}>Fulfillment details</Text>
          <Text style={styles.fulfillmentSubtitle}>
            Switch modes, review timing, and keep checkout synced from here.
          </Text>
        </View>
        <Pressable
          onPress={() => onOpenFulfillmentSheet()}
          style={styles.fulfillmentPrimaryAction}
        >
          <Text style={styles.fulfillmentPrimaryActionText}>Change mode</Text>
          <Icon color={theme.colors.primary} name="chevron-forward" size={14} />
        </Pressable>
      </View>

      <View style={styles.fulfillmentToggle}>
        <Pressable
          onPress={() => onFulfillmentModePress('DELIVERY')}
          style={[
            styles.fulfillmentToggleButton,
            fulfillmentType === 'DELIVERY' &&
              styles.fulfillmentToggleButtonActive,
            !deliveryEnabled && styles.fulfillmentToggleButtonDisabled,
          ]}
        >
          <Icon
            color={
              fulfillmentType === 'DELIVERY'
                ? theme.mode === 'dark'
                  ? theme.colors.primary
                  : theme.colors.white
                : deliveryEnabled
                ? theme.colors.primary
                : theme.colors.hint
            }
            name="bicycle-outline"
            size={16}
          />
          <Text
            style={[
              styles.fulfillmentToggleText,
              fulfillmentType === 'DELIVERY' &&
                styles.fulfillmentToggleTextActive,
              !deliveryEnabled && styles.fulfillmentToggleTextDisabled,
            ]}
          >
            Delivery
          </Text>
        </Pressable>
        <Pressable
          onPress={() => onFulfillmentModePress('PICKUP')}
          style={[
            styles.fulfillmentToggleButton,
            fulfillmentType === 'PICKUP' &&
              styles.fulfillmentToggleButtonActive,
            !pickupEnabled && styles.fulfillmentToggleButtonDisabled,
          ]}
        >
          <Icon
            color={
              fulfillmentType === 'PICKUP'
                ? theme.mode === 'dark'
                  ? theme.colors.primary
                  : theme.colors.white
                : pickupEnabled
                ? theme.colors.primary
                : theme.colors.hint
            }
            name="storefront-outline"
            size={16}
          />
          <Text
            style={[
              styles.fulfillmentToggleText,
              fulfillmentType === 'PICKUP' &&
                styles.fulfillmentToggleTextActive,
              !pickupEnabled && styles.fulfillmentToggleTextDisabled,
            ]}
          >
            Pickup
          </Text>
        </Pressable>
      </View>

      <View style={styles.fulfillmentSelectedCard}>
        <View style={styles.fulfillmentSelectedHeader}>
          <View style={styles.fulfillmentSelectedIconWrap}>
            <Icon
              color={theme.colors.primary}
              name={
                fulfillmentType === 'DELIVERY'
                  ? 'bicycle-outline'
                  : 'storefront-outline'
              }
              size={18}
            />
          </View>
          <View style={styles.fulfillmentSelectedCopy}>
            <Text style={styles.fulfillmentSelectedEyebrow}>Selected mode</Text>
            <Text style={styles.fulfillmentSelectedTitle}>
              {fulfillmentChipLabel}
            </Text>
            <Text style={styles.fulfillmentSelectedSubtitle}>
              {timingSupportingLabel}
            </Text>
          </View>
          <View style={styles.fulfillmentSummaryPill}>
            <Text style={styles.fulfillmentSummaryPillText}>{timingLabel}</Text>
          </View>
        </View>

        {!activeFulfillmentAvailable ? (
          <View style={styles.fulfillmentWarning}>
            <Icon
              color={theme.colors.primary}
              name="alert-circle-outline"
              size={14}
            />
            <Text style={styles.fulfillmentWarningText}>
              {activeFulfillmentReason ??
                'This branch cannot fulfill the selected order type right now.'}
            </Text>
          </View>
        ) : null}

        {fulfillmentType === 'DELIVERY' ? (
          <View
            style={[
              styles.fulfillmentBody,
              showMissingDeliveryAddressWarning &&
                styles.fulfillmentBodyWarning,
            ]}
          >
            <View style={styles.fulfillmentInfo}>
              <Text style={styles.fulfillmentLabel}>
                {showMissingDeliveryAddressWarning
                  ? 'Delivery Address Required'
                  : 'Delivery address'}
              </Text>
              {showMissingDeliveryAddressWarning ? (
                <View style={styles.fulfillmentWarningBanner}>
                  <Icon
                    color={theme.colors.primary}
                    name="warning-outline"
                    size={15}
                  />
                  <Text style={styles.fulfillmentWarningTextCard}>
                    Please add a delivery address before continuing to checkout.
                  </Text>
                </View>
              ) : null}
              {deliveryAddress.trim() ? (
                <Text
                  style={[
                    styles.fulfillmentValue,
                    showMissingDeliveryAddressWarning &&
                      styles.fulfillmentValueWarning,
                  ]}
                >
                  {deliveryAddress.trim()}
                </Text>
              ) : null}
            </View>
            <Pressable
              onPress={() => onChangeAddress()}
              style={[
                styles.fulfillmentAction,
                showMissingDeliveryAddressWarning &&
                  styles.fulfillmentActionHighlighted,
              ]}
            >
              <Text
                style={[
                  styles.fulfillmentActionText,
                  showMissingDeliveryAddressWarning &&
                    styles.fulfillmentActionTextHighlighted,
                ]}
              >
                {deliveryAddress.trim() ? 'Change' : 'Select'}
              </Text>
            </Pressable>
          </View>
        ) : (
          <View style={styles.fulfillmentBody}>
            <View style={styles.fulfillmentInfo}>
              <Text style={styles.fulfillmentLabel}>Pickup branch</Text>
              <Text style={styles.fulfillmentValue}>{pickupAddress}</Text>
            </View>
            <View style={styles.fulfillmentMetaPill}>
              <Text style={styles.fulfillmentMetaText}>
                {scheduleType === 'SCHEDULED'
                  ? 'Slot reserved'
                  : 'No delivery fee'}
              </Text>
            </View>
          </View>
        )}
      </View>
    </View>
  );
}

export const CartFulfillmentCard = React.memo(CartFulfillmentCardComponent);
