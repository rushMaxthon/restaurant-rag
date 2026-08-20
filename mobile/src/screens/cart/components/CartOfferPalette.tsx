import React, { useCallback } from 'react';
import {
  FlatList,
  Pressable,
  Text,
  View,
  type ListRenderItem,
} from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { formatCurrency, toNumber } from '@services/api';
import { getOfferPalette } from '@components/offers/offerPalette';
import { useTheme, useThemedStyles } from '@/theme';
import type {
  AppliedPersonalizedOffer,
  PersonalizedOfferCard,
  PersonalizedOfferPreview,
} from '@/types/app';
import { createStyles } from '../styles';
import {
  formatOfferEndsLabel,
  getOfferIconName,
  hexToRgba,
  matchesAppliedOffer,
  toAppliedOffer,
} from '../offerCardHelpers';

interface CartOfferPaletteProps {
  activePersonalizedOffer: AppliedPersonalizedOffer | null;
  offerCardWidth: number;
  offerPaletteLoading: boolean;
  offerPreviewsByCardId: Record<string, PersonalizedOfferPreview>;
  restaurantOffers: PersonalizedOfferCard[];
  setSelectedPersonalizedOffer: (
    offer: AppliedPersonalizedOffer | null,
  ) => void;
}

/**
 * The horizontal "offers for this cart" strip.
 *
 * Split out of `CartScreen` so unrelated screen state - typing special
 * instructions, expanding order details - no longer re-renders this list or
 * re-runs its per-card palette maths.
 */
function CartOfferPaletteComponent({
  activePersonalizedOffer,
  offerCardWidth,
  offerPaletteLoading,
  offerPreviewsByCardId,
  restaurantOffers,
  setSelectedPersonalizedOffer,
}: CartOfferPaletteProps): React.JSX.Element | null {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);

  const renderOfferPaletteItem = useCallback<
    ListRenderItem<PersonalizedOfferCard>
  >(
    ({ item }) => {
      const palette = getOfferPalette(
        {
          offer_type: item.offer_type,
          audience_type: item.audience_type,
          cuisine_type: item.cuisine_type,
          discount_type: item.discount_type,
        },
        theme.mode,
      );
      const preview = offerPreviewsByCardId[item.id] ?? null;
      const isSelected = matchesAppliedOffer(item, activePersonalizedOffer);
      const isApplied = Boolean(isSelected && preview?.eligible);
      const isUnlocked = Boolean(!isApplied && preview?.eligible);
      const amountRemaining = toNumber(preview?.amount_to_unlock ?? 0);
      const statusCopy = offerPaletteLoading
        ? 'Checking this offer...'
        : isApplied
        ? preview?.message ?? 'Discount applied to this cart.'
        : isUnlocked
        ? preview?.message ?? 'Ready to apply'
        : amountRemaining > 0
        ? `Add ${formatCurrency(amountRemaining)} more to unlock`
        : preview?.message ?? 'Not eligible for this cart yet';
      const metaParts = [
        Number(item.minimum_order_amount) > 0
          ? `Min ${formatCurrency(item.minimum_order_amount)}`
          : 'No min order',
      ];
      const endsLabel = formatOfferEndsLabel(item.expires_at);
      if (endsLabel) {
        metaParts.push(endsLabel);
      }
      const badgeCopy = isApplied
        ? 'Applied'
        : isUnlocked
        ? 'Unlocked'
        : offerPaletteLoading && !preview
        ? 'Checking'
        : 'Locked';
      const darkMode = theme.mode === 'dark';
      const cardBackgroundColor = darkMode
        ? isApplied
          ? hexToRgba(palette.accent, 0.18)
          : isUnlocked
          ? hexToRgba(palette.accent, 0.13)
          : hexToRgba(palette.accent, 0.08)
        : palette.surface;
      const cardBorderColor = darkMode
        ? isApplied
          ? hexToRgba(palette.accent, 0.92)
          : isUnlocked
          ? hexToRgba(palette.accent, 0.58)
          : hexToRgba(palette.accent, 0.26)
        : isApplied
        ? palette.accent
        : `${palette.accent}22`;
      const iconSurface = darkMode
        ? hexToRgba(palette.accent, 0.12)
        : palette.iconSurface;
      const titleColor = darkMode
        ? isApplied || isUnlocked
          ? '#F5FFFC'
          : '#EEF7F4'
        : theme.colors.text;
      const discountColor = darkMode
        ? isApplied
          ? '#9BFFF0'
          : isUnlocked
          ? '#7EF2DE'
          : '#40D9C2'
        : palette.accent;
      const statusBadgeBackground = darkMode
        ? isApplied
          ? hexToRgba('#32D7BF', 0.2)
          : isUnlocked
          ? hexToRgba('#22C7B0', 0.16)
          : 'rgba(255, 255, 255, 0.08)'
        : isApplied
        ? palette.badgeSurface
        : isUnlocked
        ? theme.colors.primarySoft
        : theme.colors.surfaceRaised;
      const statusTextColor = darkMode
        ? isApplied
          ? '#9BFFF0'
          : isUnlocked
          ? '#6DE9D4'
          : '#BFC9CF'
        : isApplied || isUnlocked
        ? palette.accent
        : theme.colors.hint;
      const messageColor = darkMode
        ? isApplied || isUnlocked
          ? '#D8F7F1'
          : '#B7C5CA'
        : theme.colors.secondaryText;
      const metaColor = darkMode ? '#9FB0B6' : theme.colors.hint;
      const actionBackgroundColor = darkMode
        ? isApplied || isUnlocked
          ? 'rgba(255, 255, 255, 0.94)'
          : hexToRgba(palette.accent, 0.12)
        : palette.ctaSurface;
      const iconColor = darkMode ? discountColor : palette.iconText;
      const actionTextColor = darkMode
        ? isApplied || isUnlocked
          ? '#0F6F63'
          : '#C5D0D4'
        : isApplied || isUnlocked
        ? palette.ctaText
        : theme.colors.hint;

      return (
        <View
          style={[
            styles.offerPaletteCard,
            {
              width: offerCardWidth,
              backgroundColor: cardBackgroundColor,
              borderColor: cardBorderColor,
            },
          ]}
        >
          <View style={styles.offerPaletteRowTop}>
            <View
              style={[
                styles.offerPaletteIconWrap,
                { backgroundColor: iconSurface },
              ]}
            >
              <Icon color={iconColor} name={getOfferIconName(item)} size={16} />
            </View>
            <View style={styles.offerPaletteCopy}>
              <View style={styles.offerPaletteTitleRow}>
                <Text
                  numberOfLines={1}
                  style={[
                    styles.offerPaletteDiscountLabel,
                    { color: discountColor },
                  ]}
                >
                  {item.discount_label ?? item.offer_name}
                </Text>
                <View
                  style={[
                    styles.offerPaletteStatusBadge,
                    {
                      backgroundColor: statusBadgeBackground,
                    },
                  ]}
                >
                  <Text
                    style={[
                      styles.offerPaletteStatusText,
                      { color: statusTextColor },
                    ]}
                  >
                    {badgeCopy}
                  </Text>
                </View>
              </View>
              <Text
                numberOfLines={2}
                style={[styles.offerPaletteOfferTitle, { color: titleColor }]}
              >
                {item.title}
              </Text>
              <Text
                style={[styles.offerPaletteMessage, { color: messageColor }]}
              >
                {statusCopy}
              </Text>
            </View>
          </View>

          <View style={styles.offerPaletteFooter}>
            <View style={styles.offerPaletteMetaBlock}>
              <Text style={[styles.offerPaletteMeta, { color: metaColor }]}>
                {metaParts.join(' • ')}
              </Text>
              <Text
                numberOfLines={1}
                style={[styles.offerPaletteRestaurant, { color: metaColor }]}
              >
                {item.restaurant_name}
              </Text>
            </View>
            {isApplied ? (
              <Pressable
                onPress={() => setSelectedPersonalizedOffer(null)}
                style={[
                  styles.offerPaletteActionButton,
                  { backgroundColor: actionBackgroundColor },
                ]}
              >
                <Text
                  style={[
                    styles.offerPaletteActionButtonText,
                    { color: actionTextColor },
                  ]}
                >
                  Remove
                </Text>
              </Pressable>
            ) : isUnlocked ? (
              <Pressable
                onPress={() =>
                  setSelectedPersonalizedOffer(toAppliedOffer(item))
                }
                style={[
                  styles.offerPaletteActionButton,
                  { backgroundColor: actionBackgroundColor },
                ]}
              >
                <Text
                  style={[
                    styles.offerPaletteActionButtonText,
                    { color: actionTextColor },
                  ]}
                >
                  Apply
                </Text>
              </Pressable>
            ) : isSelected ? (
              <Pressable
                onPress={() => setSelectedPersonalizedOffer(null)}
                style={[
                  styles.offerPaletteActionButton,
                  {
                    backgroundColor:
                      theme.mode === 'dark'
                        ? hexToRgba(palette.accent, 0.12)
                        : '#FFF4EC',
                  },
                ]}
              >
                <Text
                  style={[
                    styles.offerPaletteActionButtonText,
                    { color: theme.colors.primary },
                  ]}
                >
                  Remove
                </Text>
              </Pressable>
            ) : (
              <View style={styles.offerPaletteLockedPill}>
                <Text
                  style={[
                    styles.offerPaletteLockedText,
                    {
                      color: darkMode ? '#BFC9CF' : theme.colors.hint,
                    },
                  ]}
                >
                  {offerPaletteLoading && !preview ? 'Checking' : 'Locked'}
                </Text>
              </View>
            )}
          </View>
        </View>
      );
    },
    [
      activePersonalizedOffer,
      offerCardWidth,
      offerPaletteLoading,
      offerPreviewsByCardId,
      setSelectedPersonalizedOffer,
      styles,
      theme,
    ],
  );

  const renderSeparator = useCallback(
    () => <View style={styles.offerPaletteSpacer} />,
    [styles],
  );

  if (restaurantOffers.length === 0) {
    return null;
  }

  return (
    <View style={styles.offerPaletteSection}>
      <View style={styles.offerPaletteHeader}>
        <View style={styles.offerPaletteHeaderTop}>
          <Text style={styles.offerPaletteHeaderTitle}>
            Offers for this cart
          </Text>
          <Text style={styles.offerPaletteHeaderCount}>
            {restaurantOffers.length}
          </Text>
        </View>
        <Text style={styles.offerPaletteHeaderSubtitle}>
          Locked offers stay visible and unlock as your cart grows.
        </Text>
      </View>
      <FlatList
        horizontal
        contentContainerStyle={styles.offerPaletteList}
        data={restaurantOffers}
        decelerationRate="fast"
        disableIntervalMomentum
        keyExtractor={item => item.id}
        snapToAlignment="start"
        snapToInterval={offerCardWidth + 12}
        renderItem={renderOfferPaletteItem}
        showsHorizontalScrollIndicator={false}
        ItemSeparatorComponent={renderSeparator}
      />
    </View>
  );
}

export const CartOfferPalette = React.memo(CartOfferPaletteComponent);
