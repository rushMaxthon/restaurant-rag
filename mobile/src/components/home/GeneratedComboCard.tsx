import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { formatCurrency, toNumber } from '@services/api';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { GeneratedCombo } from '@/types/app';

export const GENERATED_COMBO_CARD_GAP = 12;
export const GENERATED_COMBO_CARD_MIN_WIDTH = 208;
export const GENERATED_COMBO_CARD_MAX_WIDTH = 276;

export function getGeneratedComboCardMetrics(screenWidth: number) {
  const cardWidth = Math.min(
    Math.max(Math.round(screenWidth * 0.68), GENERATED_COMBO_CARD_MIN_WIDTH),
    GENERATED_COMBO_CARD_MAX_WIDTH,
  );
  const cardHeight = 0; // Allow dynamic height
  const heroHeight = 0;

  return {
    cardWidth,
    cardHeight,
    heroHeight,
    interval: cardWidth + GENERATED_COMBO_CARD_GAP,
  };
}

interface GeneratedComboCardProps {
  combo: GeneratedCombo;
  onPress: (combo: GeneratedCombo) => void;
  onAddCombo: (combo: GeneratedCombo) => void;
  cardWidth?: number;
  cardHeight?: number;
  heroHeight?: number;
  showHeartButton?: boolean;
}

type ComboBadge = {
  backgroundColor: string;
  iconColor: string;
  iconName: string;
  label: string;
  textColor: string;
};

function getComboBadge(
  theme: AppTheme,
  combo: GeneratedCombo,
): ComboBadge | null {
  const savings = toNumber(combo.savings_amount);
  const originalTotal = toNumber(combo.original_total_price);
  const savingsRate = originalTotal > 0 ? savings / originalTotal : 0;
  const confidence = toNumber(combo.confidence_score);

  if (savingsRate >= 0.15 || savings >= 60) {
    return {
      label: 'Best Value',
      iconName: 'star',
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : '#FFF4E6',
      textColor: '#FF7A00',
      iconColor: '#FF9A1F',
    };
  }

  if (combo.order_count >= 100 || confidence >= 0.72) {
    return {
      label: 'Trending',
      iconName: 'flame',
      backgroundColor: '#FFF0E8',
      textColor: theme.colors.primary,
      iconColor: theme.colors.primary,
    };
  }

  return null;
}

function GeneratedComboCardComponent({
  combo,
  onPress,
  onAddCombo,
  cardWidth = GENERATED_COMBO_CARD_MAX_WIDTH,
  showHeartButton = true,
}: GeneratedComboCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const badge = getComboBadge(theme, combo);
  const originalPrice = Math.max(
    toNumber(combo.original_total_price),
    toNumber(combo.suggested_combo_price),
  );
  const orderedCount = Math.max(combo.order_count, combo.unique_user_count);

  const restaurantTint =
    badge?.label === 'Best Value'
      ? theme.mode === 'dark'
        ? theme.colors.surfaceAlt
        : '#FFF6E8'
      : theme.mode === 'dark'
      ? theme.colors.primarySoft
      : '#FFF1E8';
  const restaurantIconColor =
    badge?.label === 'Best Value' ? theme.colors.warning : theme.colors.primary;

  return (
    <View style={[styles.shadowWrap, { width: cardWidth }]}>
      <Pressable
        onPress={() => onPress(combo)}
        style={({ pressed }) => [
          styles.card,
          pressed ? styles.cardPressed : null,
        ]}
      >
        <View style={styles.heroGlowPrimary} />
        <View style={styles.heroGlowSecondary} />

        <View style={styles.contentContainer}>
          <View style={styles.headerRow}>
            {badge ? (
              <View
                style={[
                  styles.statusBadge,
                  { backgroundColor: badge.backgroundColor },
                ]}
              >
                <Icon color={badge.iconColor} name={badge.iconName} size={12} />
                <Text
                  style={[styles.statusBadgeText, { color: badge.textColor }]}
                >
                  {badge.label}
                </Text>
              </View>
            ) : (
              <View />
            )}
            {showHeartButton ? (
              <View style={styles.heartButton}>
                <Icon color="#101828" name="heart-outline" size={18} />
              </View>
            ) : (
              <View style={styles.headerSpacer} />
            )}
          </View>

          <View style={styles.titleContainer}>
            <Text numberOfLines={2} style={styles.title}>
              {combo.combo_name}
            </Text>
            {/* Restaurant and social proof share one line: the wider card has
                room for both, and it saves a full row of height. */}
            <View style={styles.metaRow}>
              <View
                style={[
                  styles.restaurantIconWrap,
                  { backgroundColor: restaurantTint },
                ]}
              >
                <Icon
                  color={restaurantIconColor}
                  name="storefront-outline"
                  size={11}
                />
              </View>
              <Text numberOfLines={1} style={styles.restaurantName}>
                {combo.restaurant_name}
              </Text>
              <View style={styles.orderedPill}>
                <Icon color={theme.colors.success} name="people" size={11} />
                <Text style={styles.orderedText}>{orderedCount}+ ordered</Text>
              </View>
            </View>
          </View>

          <View style={styles.bottomBlock}>
            <View style={styles.footerRow}>
              <View style={styles.priceRow}>
                <Text style={styles.currentPrice}>
                  {formatCurrency(combo.suggested_combo_price)}
                </Text>
                {originalPrice > toNumber(combo.suggested_combo_price) ? (
                  <Text style={styles.oldPrice}>
                    {formatCurrency(originalPrice)}
                  </Text>
                ) : null}
              </View>

              <Pressable
                hitSlop={8}
                onPress={() => onAddCombo(combo)}
                style={({ pressed }) => [
                  styles.addButton,
                  pressed ? styles.addButtonPressed : null,
                ]}
              >
                <Icon color={theme.colors.white} name="add" size={20} />
              </Pressable>
            </View>
          </View>
        </View>
      </Pressable>
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    shadowWrap: {
      marginRight: GENERATED_COMBO_CARD_GAP,
    },
    card: {
      flex: 1,
      borderRadius: 20,
      backgroundColor: theme.mode === 'dark' ? theme.colors.surface : '#FFFCF7',
      borderWidth: 1,
      borderColor: theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.05,
      shadowOffset: { width: 0, height: 6 },
      shadowRadius: 12,
      elevation: 3,
      overflow: 'hidden',
    },
    cardPressed: {
      opacity: 0.96,
    },
    heroGlowPrimary: {
      position: 'absolute',
      top: -30,
      right: -30,
      width: 140,
      height: 140,
      borderRadius: 70,
      backgroundColor: 'rgba(255, 82, 0, 0.06)',
    },
    heroGlowSecondary: {
      position: 'absolute',
      top: 40,
      left: -20,
      width: 80,
      height: 80,
      borderRadius: 40,
      backgroundColor: 'rgba(255, 197, 143, 0.08)',
    },
    contentContainer: {
      flex: 1,
      paddingHorizontal: 12,
      paddingVertical: 11,
      justifyContent: 'space-between',
    },
    headerRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      alignItems: 'center',
      marginBottom: 8,
    },
    statusBadge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
      borderRadius: 999,
      paddingHorizontal: 8,
      paddingVertical: 3,
    },
    statusBadgeText: {
      fontSize: 10,
      fontWeight: '800',
    },
    heartButton: {
      width: 26,
      height: 26,
      borderRadius: 13,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255,255,255,0.8)',
      borderWidth: 1,
      borderColor: theme.colors.border,
      alignItems: 'center',
      justifyContent: 'center',
    },
    headerSpacer: {
      width: 26,
      height: 26,
    },
    titleContainer: {
      marginBottom: 10,
    },
    title: {
      color: theme.colors.text,
      fontSize: 14,
      lineHeight: 18,
      fontWeight: '800',
      letterSpacing: -0.3,
      marginBottom: 6,
      // Two lines fixed, so cards in the same rail line up rather than
      // stepping up and down with the length of each combo name.
      minHeight: 36,
    },
    metaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 5,
    },
    restaurantIconWrap: {
      width: 17,
      height: 17,
      borderRadius: 9,
      alignItems: 'center',
      justifyContent: 'center',
    },
    restaurantName: {
      flexShrink: 1,
      color: theme.colors.secondaryText,
      fontSize: 11,
      fontWeight: '700',
    },
    orderedPill: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 3,
      borderRadius: 999,
      paddingHorizontal: 6,
      paddingVertical: 2,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : 'rgba(46, 125, 50, 0.08)',
    },
    orderedText: {
      color: theme.colors.success,
      fontSize: 10,
      fontWeight: '800',
    },
    bottomBlock: {
      marginTop: 'auto',
    },
    footerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
    },
    priceRow: {
      flexDirection: 'row',
      alignItems: 'baseline',
      gap: 6,
      flexWrap: 'wrap',
      flex: 1,
      marginRight: 8,
    },
    currentPrice: {
      color: theme.colors.primary,
      fontSize: 16,
      fontWeight: '900',
      letterSpacing: -0.4,
    },
    oldPrice: {
      color: theme.colors.hint,
      fontSize: 11,
      fontWeight: '600',
      textDecorationLine: 'line-through',
    },
    addButton: {
      width: 28,
      height: 28,
      borderRadius: 10,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
      shadowColor: theme.colors.primary,
      shadowOpacity: 0.2,
      shadowOffset: { width: 0, height: 4 },
      shadowRadius: 8,
      elevation: 3,
    },
    addButtonPressed: {
      opacity: 0.85,
      transform: [{ scale: 0.96 }],
    },
  });

const styles = createStyles(theme);

/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const GeneratedComboCard = React.memo(GeneratedComboCardComponent);
