import React, { useEffect, useRef } from 'react';
import {
  Animated,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { formatCurrency, placeholderImage } from '@services/api';
import { FavoriteIconButton } from '@components/FavoriteIconButton';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { MenuItem } from '@/types/app';
import { getNewItemBadgeMeta } from '@utils/newItemBadges';

interface MenuItemCardProps {
  item: MenuItem;
  quantity: number;
  hasOfferAvailable?: boolean;
  isFavorite: boolean;
  favoritePending?: boolean;
  onAdd: (item: MenuItem) => void;
  onDecrease: (itemId: string) => void;
  onOpen: (itemId: string) => void;
  onToggleFavorite: (item: MenuItem) => void;
}

function MenuItemCardComponent({
  item,
  quantity,
  hasOfferAvailable = false,
  isFavorite,
  favoritePending = false,
  onAdd,
  onDecrease,
  onOpen,
  onToggleFavorite,
}: MenuItemCardProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const fade = useRef(new Animated.Value(0)).current;
  const translate = useRef(new Animated.Value(6)).current;
  const newItemMeta = getNewItemBadgeMeta(item);

  useEffect(() => {
    Animated.parallel([
      Animated.timing(fade, {
        toValue: 1,
        duration: 180,
        useNativeDriver: true,
      }),
      Animated.timing(translate, {
        toValue: 0,
        duration: 180,
        useNativeDriver: true,
      }),
    ]).start();
  }, [fade, translate]);

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
    <Animated.View
      style={[
        styles.card,
        {
          opacity: fade,
          transform: [{ translateY: translate }],
        },
      ]}
    >
      <Pressable onPress={handleOpen} style={styles.copy}>
        <View style={styles.badges}>
          <View
            style={[
              styles.dot,
              {
                backgroundColor: item.is_veg
                  ? theme.colors.offer
                  : theme.colors.deepRed,
              },
            ]}
          />
          {newItemMeta.label ? (
            <View style={styles.chipNew}>
              <Text style={styles.chipNewText}>{newItemMeta.label}</Text>
            </View>
          ) : null}
          {hasOfferAvailable ? (
            <View style={styles.chipOffer}>
              <Text style={styles.chipOfferText}>OFFER</Text>
            </View>
          ) : null}
        </View>

        <Text numberOfLines={1} style={styles.name}>
          {item.name}
        </Text>

        <Text numberOfLines={2} style={styles.description}>
          {item.description ??
            'Freshly prepared and ready for the next craving.'}
        </Text>

        <Text style={styles.price}>{formatCurrency(item.price)}</Text>
      </Pressable>

      <View style={styles.mediaColumn}>
        <View style={styles.mediaWrap}>
          <Pressable onPress={handleOpen}>
            <Image
              source={{ uri: item.image_url ?? placeholderImage(item.name) }}
              style={styles.image}
            />
          </Pressable>
          <View style={styles.favoriteButton}>
            <FavoriteIconButton
              active={isFavorite}
              disabled={favoritePending}
              onPress={() => onToggleFavorite(item)}
            />
          </View>
        </View>
        {quantity > 0 ? (
          <View style={styles.quantityBox}>
            <Pressable onPress={handleDecrease} style={styles.quantityButton}>
              <Text style={styles.quantityAction}>−</Text>
            </Pressable>
            <Text style={styles.quantityCount}>{quantity}</Text>
            <Pressable
              disabled={!item.is_available}
              onPress={handleAdd}
              style={[
                styles.quantityButton,
                !item.is_available ? styles.quantityButtonDisabled : null,
              ]}
            >
              <Text
                style={[
                  styles.quantityAction,
                  !item.is_available ? styles.quantityActionDisabled : null,
                ]}
              >
                +
              </Text>
            </Pressable>
          </View>
        ) : (
          <Pressable
            disabled={!item.is_available}
            onPress={handleAdd}
            style={[
              styles.addButton,
              !item.is_available ? styles.addButtonDisabled : null,
            ]}
          >
            <Text
              style={[
                styles.addButtonText,
                !item.is_available ? styles.addButtonTextDisabled : null,
              ]}
            >
              {item.is_available ? '+ ADD' : 'Sold out'}
            </Text>
          </Pressable>
        )}
      </View>
    </Animated.View>
  );
}

export const MenuItemCard = React.memo(
  MenuItemCardComponent,
  (prevProps, nextProps) =>
    prevProps.item === nextProps.item &&
    prevProps.quantity === nextProps.quantity &&
    prevProps.isFavorite === nextProps.isFavorite &&
    prevProps.favoritePending === nextProps.favoritePending &&
    prevProps.onAdd === nextProps.onAdd &&
    prevProps.onDecrease === nextProps.onDecrease &&
    prevProps.onOpen === nextProps.onOpen &&
    prevProps.onToggleFavorite === nextProps.onToggleFavorite,
);

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    card: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 12,
      paddingVertical: 14,
      borderBottomWidth: 1,
      borderBottomColor: theme.colors.divider,
      backgroundColor: theme.colors.background,
    },
    copy: {
      flex: 1,
      gap: 6,
      paddingRight: 4,
    },
    badges: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    dot: {
      width: 12,
      height: 12,
      borderRadius: 6,
    },
    chip: {
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : '#FFF3E0',
      borderRadius: 999,
      paddingHorizontal: 8,
      paddingVertical: 3,
    },
    chipNew: {
      backgroundColor: theme.colors.primarySoft,
      borderRadius: 999,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'rgba(255,82,0,0.16)',
      paddingHorizontal: 8,
      paddingVertical: 3,
    },
    chipText: {
      color: theme.colors.warning,
      fontSize: 11,
      fontWeight: '700',
    },
    chipNewText: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '700',
    },
    chipOffer: {
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(26,141,131,0.18)'
          : 'rgba(26,141,131,0.12)',
      borderRadius: 999,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark'
          ? 'rgba(26,141,131,0.26)'
          : 'rgba(26,141,131,0.18)',
      paddingHorizontal: 8,
      paddingVertical: 3,
    },
    chipOfferText: {
      color: theme.mode === 'dark' ? '#6FDBCB' : '#176E66',
      fontSize: 11,
      fontWeight: '800',
      letterSpacing: 0.3,
    },
    chipMuted: {
      backgroundColor: theme.colors.surface,
      borderRadius: 999,
      paddingHorizontal: 8,
      paddingVertical: 3,
    },
    chipMutedText: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      fontWeight: '700',
    },
    name: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    description: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    price: {
      marginTop: 2,
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '700',
    },
    mediaColumn: {
      width: 88,
      alignItems: 'center',
      gap: 8,
    },
    mediaWrap: {
      position: 'relative',
    },
    favoriteButton: {
      position: 'absolute',
      top: 6,
      right: 6,
    },
    image: {
      width: 80,
      height: 80,
      borderRadius: 10,
      backgroundColor: theme.colors.card,
    },
    addButton: {
      minWidth: 72,
      minHeight: 30,
      paddingHorizontal: 12,
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark'
          ? theme.colors.chipBorder
          : 'rgba(255, 82, 0, 0.15)',
      alignItems: 'center',
      justifyContent: 'center',
    },
    addButtonDisabled: {
      backgroundColor: theme.colors.card,
      borderColor: theme.colors.border,
    },
    addButtonText: {
      color: theme.colors.primary,
      fontSize: 12,
      fontWeight: '800',
    },
    addButtonTextDisabled: {
      color: theme.colors.hint,
    },
    quantityBox: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      paddingHorizontal: 8,
      paddingVertical: 6,
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.chipBorder : 'transparent',
    },
    quantityButton: {
      width: 24,
      height: 24,
      borderRadius: 12,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
    },
    quantityButtonDisabled: {
      backgroundColor: theme.colors.card,
    },
    quantityAction: {
      color: theme.colors.primary,
      fontSize: 16,
      fontWeight: '800',
    },
    quantityActionDisabled: {
      color: theme.colors.hint,
    },
    quantityCount: {
      minWidth: 16,
      textAlign: 'center',
      color: theme.colors.text,
      fontSize: 12,
      fontWeight: '800',
    },
  });

const styles = createStyles(theme);
