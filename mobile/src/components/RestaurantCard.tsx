import React from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { formatCurrency, placeholderImage, toNumber } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { Restaurant } from '@/types/app';

interface RestaurantCardProps {
  restaurant: Restaurant;
  /**
   * Receives the restaurant, so callers can pass one stable handler for a
   * whole list instead of a fresh closure per row.
   */
  onPress: (restaurant: Restaurant) => void;
  variant?: 'full' | 'compact';
}

function RestaurantCardComponent({
  restaurant,
  onPress,
  variant = 'full',
}: RestaurantCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const handlePress = React.useCallback(
    () => onPress(restaurant),
    [onPress, restaurant],
  );
  const compact = variant === 'compact';
  const etaMinutes = 18 + (restaurant.name.length % 18);
  const priceBand =
    toNumber(restaurant.minimum_order_amount) > 300 ? '₹₹₹' : '₹₹';

  return (
    <Pressable
      onPress={handlePress}
      style={({ pressed }) => [
        styles.card,
        compact ? styles.cardCompact : null,
        pressed ? styles.cardPressed : null,
      ]}
    >
      <View style={compact ? styles.mediaFrameCompact : styles.mediaFrame}>
        <Image
          source={{
            uri:
              restaurant.cover_image_url ?? placeholderImage(restaurant.name),
          }}
          style={compact ? styles.imageCompact : styles.image}
        />
        <View style={compact ? styles.overlayCompact : styles.overlay} />
        <View
          style={[
            compact ? styles.statusChipCompact : styles.statusChip,
            restaurant.is_open ? styles.statusOpen : styles.statusClosed,
          ]}
        >
          <Text style={compact ? styles.statusTextCompact : styles.statusText}>
            {restaurant.is_open ? 'Open' : 'Closed'}
          </Text>
        </View>
      </View>

      <View style={compact ? styles.bodyCompact : styles.body}>
        <View style={styles.nameRow}>
          <Text
            numberOfLines={1}
            style={compact ? styles.nameCompact : styles.name}
          >
            {restaurant.name}
          </Text>
          {!compact && (
            <View style={styles.etaBadge}>
              <Icon
                name="time-outline"
                size={12}
                color={theme.colors.primary}
              />
              <Text style={styles.etaText}>{etaMinutes} min</Text>
            </View>
          )}
        </View>

        <View style={compact ? styles.metaRowCompact : styles.metaRow}>
          <Text
            numberOfLines={1}
            style={compact ? styles.metaCompact : styles.meta}
          >
            {restaurant.cuisine_type} • {restaurant.city} • {priceBand}
            {compact ? ` • ${etaMinutes} mins` : ''}
          </Text>
        </View>

        <View style={compact ? styles.tagRowCompact : styles.tagRow}>
          <View style={compact ? styles.feeTagCompact : styles.feeTag}>
            <Icon
              name="bicycle-outline"
              size={compact ? 12 : 14}
              color={theme.colors.primary}
            />
            <Text style={compact ? styles.feeTextCompact : styles.feeText}>
              {toNumber(restaurant.delivery_fee) > 0
                ? `${formatCurrency(restaurant.delivery_fee)} delivery`
                : 'Free delivery'}
            </Text>
          </View>
        </View>
      </View>
    </Pressable>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    card: {
      borderRadius: 20,
      overflow: 'hidden',
      backgroundColor: theme.colors.surfaceRaised,
      marginBottom: 16,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 6 },
      shadowRadius: 14,
      elevation: 3,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    cardPressed: {
      opacity: 0.96,
      transform: [{ scale: 0.98 }],
    },
    cardCompact: {
      width: 272,
      marginRight: 12,
      marginBottom: 0,
      flexDirection: 'row',
      padding: 10,
      gap: 12,
      alignItems: 'center',
      borderRadius: 16,
    },
    mediaFrame: {
      position: 'relative',
    },
    mediaFrameCompact: {
      width: 80,
      height: 80,
      borderRadius: 12,
      overflow: 'hidden',
      position: 'relative',
    },
    image: {
      width: '100%',
      height: 136,
    },
    imageCompact: {
      width: '100%',
      height: '100%',
    },
    overlay: {
      ...StyleSheet.absoluteFill,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.darkOverlay
          : 'rgba(20,24,38,0.12)',
    },
    overlayCompact: {
      ...StyleSheet.absoluteFill,
      backgroundColor:
        theme.mode === 'dark' ? 'rgba(8, 10, 14, 0.22)' : 'rgba(20,24,38,0.06)',
    },
    statusChip: {
      position: 'absolute',
      top: 0,
      left: 0,
      borderBottomRightRadius: 12,
      paddingHorizontal: 12,
      paddingVertical: 6,
    },
    statusChipCompact: {
      position: 'absolute',
      top: 0,
      left: 0,
      borderBottomRightRadius: 8,
      paddingHorizontal: 6,
      paddingVertical: 3,
    },
    statusOpen: {
      backgroundColor: 'rgba(20,95,52,0.94)',
    },
    statusClosed: {
      backgroundColor: 'rgba(101,36,30,0.94)',
    },
    statusText: {
      color: theme.colors.white,
      fontWeight: '800',
      fontSize: 11,
    },
    statusTextCompact: {
      color: theme.colors.white,
      fontWeight: '800',
      fontSize: 8,
    },
    body: {
      padding: 14,
      gap: 6,
    },
    bodyCompact: {
      flex: 1,
      justifyContent: 'center',
      padding: 0,
      gap: 4,
    },
    nameRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      gap: 12,
    },
    name: {
      color: theme.colors.text,
      fontSize: 17,
      fontWeight: '800',
      letterSpacing: -0.3,
      flex: 1,
    },
    nameCompact: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
      letterSpacing: -0.3,
    },
    etaBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      backgroundColor: theme.mode === 'dark' ? theme.colors.chip : '#FFF4E6',
      paddingHorizontal: 8,
      paddingVertical: 5,
      borderRadius: 8,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
    },
    etaText: {
      color: theme.colors.primary,
      fontWeight: '800',
      fontSize: 11,
    },
    metaRow: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    metaRowCompact: {
      flexDirection: 'row',
      alignItems: 'center',
    },
    meta: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '500',
    },
    metaCompact: {
      color: theme.colors.secondaryText,
      fontSize: 11,
    },
    tagRow: {
      flexDirection: 'row',
      alignItems: 'center',
      marginTop: 2,
    },
    tagRowCompact: {
      flexDirection: 'row',
      alignItems: 'center',
      marginTop: 2,
    },
    feeTag: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      borderRadius: 8,
      backgroundColor: theme.colors.cream,
      paddingHorizontal: 8,
      paddingVertical: 5,
    },
    feeTagCompact: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      borderRadius: 6,
      backgroundColor: theme.colors.cream,
      paddingHorizontal: 6,
      paddingVertical: 3,
    },
    feeText: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '700',
    },
    feeTextCompact: {
      color: theme.colors.primary,
      fontSize: 10,
      fontWeight: '700',
    },
  });


/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const RestaurantCard = React.memo(RestaurantCardComponent);
