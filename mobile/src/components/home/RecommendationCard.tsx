import React from 'react';
import {
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
} from 'react-native';
import { formatCurrency, placeholderImage } from '@services/api';
import { FavoriteIconButton } from '@components/FavoriteIconButton';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RecommendationItem } from '@/types/app';
import type { GestureResponderEvent } from 'react-native';
import { getNewItemBadgeMeta } from '@utils/newItemBadges';

interface RecommendationCardProps {
  item: RecommendationItem;
  onPress: (item: RecommendationItem) => void;
  onAddToCart: (item: RecommendationItem) => void;
  onToggleFavorite: (item: RecommendationItem) => void;
  isFavorite: boolean;
  favoritePending?: boolean;
}

function RecommendationCardComponent({
  item,
  onPress,
  onAddToCart,
  onToggleFavorite,
  isFavorite,
  favoritePending = false,
}: RecommendationCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { width: screenWidth } = useWindowDimensions();
  const isAvailable = item.is_available !== false;
  const newItemMeta = getNewItemBadgeMeta(item);
  const primaryBadge = newItemMeta.label;
  const priceLabel =
    item.price_label ?? formatCurrency(item.display_price ?? item.price);
  const branchCount = Math.max(1, item.available_locations_count ?? 1);
  const branchCountLabel = `${branchCount} ${
    branchCount === 1 ? 'Branch' : 'Branches'
  }`;
  const tasteChipLabel = item.ai_badge || primaryBadge || 'Matches Your Taste';
  const priceValue = priceLabel.startsWith('From ')
    ? priceLabel.replace(/^From\s+/, '')
    : priceLabel;
  const showFromLabel = priceLabel.startsWith('From ');
  const locationLabel =
    (item.available_locations_count ?? 1) > 1
      ? item.requires_location_selection
        ? `Available at ${item.available_locations_count} locations`
        : `Nearest: ${
            item.preferred_location_name ?? item.restaurant_location.branch_name
          }`
      : item.preferred_location_name ?? item.restaurant_location.branch_name;
  const restaurantMeta = `${item.restaurant.name} • ${locationLabel}`;

  const cardWidth =
    screenWidth >= 900
      ? 308
      : screenWidth >= 700
      ? 288
      : Math.max(248, Math.min(296, Math.round(screenWidth * 0.78)));

  const handleOpenDetails = (event?: GestureResponderEvent) => {
    event?.stopPropagation();
    onPress(item);
  };

  const handleAddToCart = (event?: GestureResponderEvent) => {
    event?.stopPropagation();
    onAddToCart(item);
  };

  const handleToggleFavorite = (event?: GestureResponderEvent) => {
    event?.stopPropagation();
    onToggleFavorite(item);
  };

  return (
    <View style={[styles.card, { width: cardWidth }]}>
      <Pressable
        onPress={handleOpenDetails}
        style={({ pressed }) => [
          styles.contentButton,
          pressed ? styles.contentButtonPressed : null,
        ]}
      >
        <View style={styles.mediaFrame}>
          <View style={styles.matchBadge}>
            <Text style={styles.matchBadgeText}>
              {Math.round(item.score * 100)}% Match
            </Text>
          </View>
          <Image
            source={{ uri: item.image_url ?? placeholderImage(item.name) }}
            style={styles.image}
          />
          <View style={styles.imageScrim} />
        </View>

        <View style={styles.copyColumn}>
          <View style={styles.contentTop}>
            <View style={styles.titleRow}>
              <View
                style={[
                  styles.foodDot,
                  {
                    backgroundColor: item.is_veg
                      ? theme.colors.offer
                      : theme.colors.deepRed,
                  },
                ]}
              />
              <Text numberOfLines={2} style={styles.name}>
                {item.name}
              </Text>
            </View>
            <View style={styles.metaRow}>
              {item.category ? (
                <View style={styles.categoryChip}>
                  <Text numberOfLines={1} style={styles.categoryChipText}>
                    {item.category}
                  </Text>
                </View>
              ) : null}
              <View style={styles.tasteChip}>
                <Text numberOfLines={1} style={styles.tasteChipText}>
                  {tasteChipLabel}
                </Text>
              </View>
            </View>
          </View>

          <View style={styles.divider} />

          <Text numberOfLines={1} style={styles.locationMeta}>
            {restaurantMeta}
          </Text>

          <View style={styles.footerRow}>
            <View style={styles.priceBlock}>
              <Text style={styles.priceLabel}>
                {showFromLabel ? 'From' : 'Price'}
              </Text>
              <Text style={styles.priceValue}>{priceValue}</Text>
            </View>

            <View style={styles.branchChip}>
              <Text numberOfLines={1} style={styles.branchChipText}>
                {branchCountLabel}
              </Text>
            </View>

            <Pressable
              disabled={!isAvailable}
              onPress={handleAddToCart}
              style={[
                styles.addButton,
                !isAvailable ? styles.addButtonDisabled : null,
              ]}
            >
              <Text
                style={[
                  styles.addButtonText,
                  !isAvailable ? styles.addButtonTextDisabled : null,
                ]}
              >
                {isAvailable ? '+ Add' : 'Sold'}
              </Text>
            </Pressable>
          </View>
        </View>
      </Pressable>

      <View style={styles.favoriteWrapper} pointerEvents="box-none">
        <FavoriteIconButton
          active={isFavorite}
          disabled={favoritePending}
          onPress={() => handleToggleFavorite()}
        />
      </View>
    </View>
  );
}

export const RecommendationCard = React.memo(RecommendationCardComponent);

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    card: {
      marginRight: 10,
      borderRadius: 22,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? 'rgba(255,255,255,0.05)' : theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      shadowColor: theme.colors.shadow,
      shadowOpacity: theme.mode === 'dark' ? 0.22 : 0.06,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 18,
      elevation: 4,
      overflow: 'hidden',
    },
    contentButton: {
      padding: 0,
    },
    contentButtonPressed: {
      opacity: 0.96,
    },
    mediaFrame: {
      width: '100%',
      height: 90,
      backgroundColor: theme.colors.surfaceAlt,
      overflow: 'hidden',
      position: 'relative',
    },
    image: {
      width: '100%',
      height: '100%',
    },
    imageScrim: {
      ...StyleSheet.absoluteFill,
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(10, 12, 18, 0.08)'
          : 'rgba(14, 17, 22, 0.03)',
    },
    matchBadge: {
      position: 'absolute',
      top: 12,
      left: 12,
      zIndex: 2,
      paddingHorizontal: 12,
      paddingVertical: 7,
      borderRadius: 999,
      backgroundColor: 'rgba(17, 19, 25, 0.72)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    matchBadgeText: {
      color: theme.colors.white,
      fontSize: 10,
      fontWeight: '800',
    },
    favoriteWrapper: {
      position: 'absolute',
      top: 12,
      right: 12,
      zIndex: 10,
    },
    copyColumn: {
      paddingHorizontal: 12,
      paddingTop: 7,
      paddingBottom: 7,
    },
    contentTop: {
      gap: 3,
    },
    titleRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 7,
      paddingRight: 44,
    },
    foodDot: {
      width: 12,
      height: 12,
      borderRadius: 6,
      marginTop: 5,
    },
    name: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 15,
      lineHeight: 18,
      fontWeight: '800',
      letterSpacing: -0.5,
    },
    metaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      flexWrap: 'wrap',
      gap: 5,
    },
    categoryChip: {
      borderRadius: 999,
      paddingHorizontal: 10,
      paddingVertical: 5,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : theme.colors.card,
    },
    categoryChipText: {
      color: theme.colors.secondaryText,
      fontSize: 10,
      fontWeight: '700',
    },
    tasteChip: {
      borderRadius: 999,
      paddingHorizontal: 10,
      paddingVertical: 5,
      backgroundColor: theme.colors.primarySoft,
    },
    tasteChipText: {
      color: theme.colors.primary,
      fontSize: 10,
      fontWeight: '800',
    },
    divider: {
      height: 1,
      backgroundColor: theme.colors.divider,
      marginTop: 5,
      marginBottom: 5,
    },
    footerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 8,
    },
    priceBlock: {
      flex: 1,
      gap: 0,
    },
    priceLabel: {
      color: theme.colors.secondaryText,
      fontSize: 10,
      fontWeight: '700',
      textTransform: 'uppercase',
      letterSpacing: 0.6,
    },
    priceValue: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
      letterSpacing: -0.45,
    },
    branchChip: {
      borderRadius: 999,
      paddingHorizontal: 10,
      paddingVertical: 7,
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(72, 196, 121, 0.14)'
          : 'rgba(72, 196, 121, 0.12)',
    },
    branchChipText: {
      color: theme.colors.offer,
      fontSize: 10,
      fontWeight: '700',
    },
    locationMeta: {
      color: theme.colors.secondaryText,
      fontSize: 9,
      marginTop: 1,
      // Breathing room ahead of the price/Add row, which the removed reason
      // line used to provide.
      marginBottom: 10,
      paddingRight: 4,
    },
    addButton: {
      minWidth: 88,
      paddingVertical: 8,
      paddingHorizontal: 14,
      borderRadius: 13,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      shadowColor: theme.colors.primary,
      shadowOpacity: theme.mode === 'dark' ? 0.24 : 0.16,
      shadowOffset: { width: 0, height: 4 },
      shadowRadius: 10,
      elevation: 3,
    },
    addButtonDisabled: {
      backgroundColor: theme.colors.surfaceAlt,
    },
    addButtonText: {
      color: theme.colors.white,
      fontSize: 14,
      fontWeight: '800',
    },
    addButtonTextDisabled: {
      color: theme.colors.secondaryText,
    },
  });

const styles = createStyles(theme);
