import React, { useState } from 'react';
import { Image, Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { formatCurrency } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { MenuItem } from '@/types/app';

const MENU_GRID_GAP = 10;
const MENU_GRID_COLUMNS = 3;
/** Home content padding, 16 per side. */
const MENU_GRID_HORIZONTAL_INSET = 32;
const MENU_GRID_MAX_CARD_WIDTH = 158;

/**
 * Sizes the tiles so exactly three fit a phone row, gaps included. Floored so
 * rounding can never push the third card onto the next line; on wide screens
 * the cap keeps tiles compact and the row simply fits more of them.
 */
export function getMenuGridMetrics(screenWidth: number) {
  const available = screenWidth - MENU_GRID_HORIZONTAL_INSET;
  const cardWidth = Math.min(
    MENU_GRID_MAX_CARD_WIDTH,
    Math.floor(
      (available - MENU_GRID_GAP * (MENU_GRID_COLUMNS - 1)) / MENU_GRID_COLUMNS,
    ),
  );

  return {
    cardWidth,
    gap: MENU_GRID_GAP,
    imageHeight: Math.round(cardWidth * 0.82),
  };
}

interface MenuGridCardProps {
  item: MenuItem;
  quantity: number;
  cardWidth: number;
  imageHeight: number;
  onAdd: (item: MenuItem) => void;
  onDecrease: (itemId: string) => void;
  onOpen: (itemId: string) => void;
}

function MenuGridCardComponent({
  item,
  quantity,
  cardWidth,
  imageHeight,
  onAdd,
  onDecrease,
  onOpen,
}: MenuGridCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const [imageFailed, setImageFailed] = useState(false);
  // A missing or broken photo gets styled art rather than an empty grey box,
  // which is what most seeded dishes hit today.
  const showFallbackArt = !item.image_url || imageFailed;
  const dietColor = item.is_veg ? theme.colors.offer : theme.colors.deepRed;

  const handleOpen = () => {
    onOpen(item.id);
  };

  const handleAdd = () => {
    onAdd(item);
  };

  const handleDecrease = () => {
    onDecrease(item.id);
  };

  return (
    <View style={[styles.card, { width: cardWidth }]}>
      <Pressable
        onPress={handleOpen}
        style={({ pressed }) => [
          styles.mediaWrap,
          { height: imageHeight },
          pressed ? styles.mediaWrapPressed : null,
        ]}
      >
        {showFallbackArt ? (
          <View style={styles.fallbackArt}>
            <Icon
              color={theme.colors.primary}
              name="fast-food"
              size={Math.round(imageHeight * 0.34)}
            />
          </View>
        ) : (
          <Image
            onError={() => setImageFailed(true)}
            source={{ uri: item.image_url ?? undefined }}
            style={styles.image}
          />
        )}
        <View style={styles.mediaScrim} />

        <View style={[styles.dietBadge, { borderColor: dietColor }]}>
          <View style={[styles.dietDot, { backgroundColor: dietColor }]} />
        </View>

        {!item.is_available ? (
          <View style={styles.soldOutOverlay}>
            <Text style={styles.soldOutText}>Sold out</Text>
          </View>
        ) : quantity > 0 ? (
          <View style={styles.stepper}>
            <Pressable
              hitSlop={8}
              onPress={handleDecrease}
              style={styles.stepperButton}
            >
              <Text style={styles.stepperAction}>−</Text>
            </Pressable>
            <Text style={styles.stepperCount}>{quantity}</Text>
            <Pressable
              hitSlop={8}
              onPress={handleAdd}
              style={styles.stepperButton}
            >
              <Text style={styles.stepperAction}>+</Text>
            </Pressable>
          </View>
        ) : (
          <Pressable onPress={handleAdd} style={styles.addButton}>
            <Text style={styles.addButtonText}>ADD</Text>
            <Text style={styles.addButtonPlus}>+</Text>
          </Pressable>
        )}
      </Pressable>

      <Pressable onPress={handleOpen} style={styles.body}>
        <Text numberOfLines={2} style={styles.name}>
          {item.name}
        </Text>
        <Text style={styles.price}>{formatCurrency(item.price)}</Text>
      </Pressable>
    </View>
  );
}

export const MenuGridCard = React.memo(
  MenuGridCardComponent,
  (prevProps, nextProps) =>
    prevProps.item === nextProps.item &&
    prevProps.quantity === nextProps.quantity &&
    prevProps.cardWidth === nextProps.cardWidth &&
    prevProps.imageHeight === nextProps.imageHeight &&
    prevProps.onAdd === nextProps.onAdd &&
    prevProps.onDecrease === nextProps.onDecrease &&
    prevProps.onOpen === nextProps.onOpen,
);

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    card: {
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? 'rgba(255,255,255,0.06)' : theme.colors.border,
      shadowColor: theme.colors.shadow,
      shadowOpacity: theme.mode === 'dark' ? 0.28 : 0.08,
      shadowOffset: { width: 0, height: 6 },
      shadowRadius: 14,
      elevation: 3,
      overflow: 'hidden',
    },
    mediaWrap: {
      position: 'relative',
      backgroundColor: theme.colors.primarySoft,
    },
    mediaWrapPressed: {
      opacity: 0.94,
    },
    image: {
      width: '100%',
      height: '100%',
    },
    fallbackArt: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primarySoft,
    },
    /** Keeps the floating pill legible over bright food photography. */
    mediaScrim: {
      position: 'absolute',
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
      backgroundColor: 'rgba(17, 17, 17, 0.06)',
    },
    dietBadge: {
      position: 'absolute',
      top: 6,
      left: 6,
      width: 15,
      height: 15,
      borderRadius: 4,
      borderWidth: 1.5,
      backgroundColor: theme.colors.white,
      alignItems: 'center',
      justifyContent: 'center',
    },
    dietDot: {
      width: 7,
      height: 7,
      borderRadius: 4,
    },
    addButton: {
      position: 'absolute',
      right: 6,
      bottom: -1,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 3,
      paddingHorizontal: 11,
      paddingVertical: 5,
      borderRadius: 9,
      borderWidth: 1,
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.white,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.16,
      shadowOffset: { width: 0, height: 3 },
      shadowRadius: 6,
      elevation: 4,
    },
    addButtonText: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '900',
      letterSpacing: 0.4,
    },
    addButtonPlus: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '900',
      lineHeight: 14,
    },
    stepper: {
      position: 'absolute',
      right: 6,
      bottom: -1,
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: 4,
      paddingVertical: 3,
      borderRadius: 9,
      borderWidth: 1,
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primary,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.16,
      shadowOffset: { width: 0, height: 3 },
      shadowRadius: 6,
      elevation: 4,
    },
    stepperButton: {
      width: 20,
      alignItems: 'center',
      justifyContent: 'center',
    },
    stepperAction: {
      color: theme.colors.white,
      fontSize: 14,
      fontWeight: '900',
      lineHeight: 18,
    },
    stepperCount: {
      color: theme.colors.white,
      fontSize: 12,
      fontWeight: '900',
      minWidth: 14,
      textAlign: 'center',
    },
    soldOutOverlay: {
      position: 'absolute',
      right: 6,
      bottom: -1,
      paddingHorizontal: 10,
      paddingVertical: 5,
      borderRadius: 9,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceAlt,
    },
    soldOutText: {
      color: theme.colors.secondaryText,
      fontSize: 10,
      fontWeight: '800',
      letterSpacing: 0.3,
    },
    body: {
      paddingHorizontal: 9,
      paddingTop: 9,
      paddingBottom: 10,
      gap: 3,
    },
    name: {
      color: theme.colors.text,
      fontSize: 12,
      fontWeight: '800',
      lineHeight: 16,
      minHeight: 32,
    },
    price: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '900',
      letterSpacing: -0.3,
    },
  });
