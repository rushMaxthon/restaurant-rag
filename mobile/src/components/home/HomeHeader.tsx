import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface HomeHeaderProps {
  profileInitial: string;
  locationLabel: string;
  locationSubLabel: string;
  cartItemCount: number;
  onOpenProfile: () => void;
  onOpenLocation: () => void;
  onOpenFavorites: () => void;
  onOpenCart: () => void;
  onOpenNotifications: () => void;
}

/**
 * The sticky home header.
 *
 * Extracted because the loading and loaded branches of `HomeScreen` each
 * rendered their own copy of this markup, so the whole header unmounted and
 * remounted when the feed arrived. Memoized so feed state changes that leave
 * its props untouched do not re-render it.
 */
function HomeHeaderComponent({
  profileInitial,
  locationLabel,
  locationSubLabel,
  cartItemCount,
  onOpenProfile,
  onOpenLocation,
  onOpenFavorites,
  onOpenCart,
  onOpenNotifications,
}: HomeHeaderProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.stickyHeader}>
      <Pressable onPress={onOpenProfile} style={styles.profileButton}>
        {profileInitial ? (
          <Text style={styles.profileInitial}>{profileInitial}</Text>
        ) : (
          <Icon color={theme.colors.primary} name="person-outline" size={20} />
        )}
      </Pressable>

      <Pressable onPress={onOpenLocation} style={styles.headerLocationCard}>
        <View style={styles.headerLocationCopy}>
          <Text numberOfLines={1} style={styles.headerLocationText}>
            {locationLabel}
          </Text>
          <Text numberOfLines={1} style={styles.headerLocationSubText}>
            {locationSubLabel}
          </Text>
        </View>
        <Icon color={theme.colors.hint} name="chevron-down" size={16} />
      </Pressable>

      <View style={styles.headerActions}>
        <Pressable onPress={onOpenFavorites} style={styles.headerIconButton}>
          <Icon color={theme.colors.text} name="heart-outline" size={19} />
        </Pressable>
        <Pressable onPress={onOpenCart} style={styles.headerIconButton}>
          <Icon color={theme.colors.text} name="bag-handle-outline" size={19} />
          {cartItemCount > 0 ? (
            <View style={styles.cartBadge}>
              <Text style={styles.cartBadgeText}>
                {cartItemCount > 9 ? '9+' : cartItemCount}
              </Text>
            </View>
          ) : null}
        </Pressable>
        <Pressable
          onPress={onOpenNotifications}
          style={styles.headerIconButton}
        >
          <Icon
            color={theme.colors.text}
            name="notifications-outline"
            size={19}
          />
        </Pressable>
      </View>
    </View>
  );
}

export const HomeHeader = React.memo(HomeHeaderComponent);

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    stickyHeader: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      paddingHorizontal: 16,
      paddingTop: 6,
      paddingBottom: 10,
      backgroundColor: theme.colors.background,
    },
    profileButton: {
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor: theme.mode === 'dark' ? theme.colors.border : '#FFD8C7',
      alignItems: 'center',
      justifyContent: 'center',
      flexShrink: 0,
    },
    profileInitial: {
      color: theme.colors.primary,
      fontSize: 16,
      fontWeight: '900',
    },
    headerLocationCard: {
      flex: 1,
      minWidth: 0,
      minHeight: 48,
      borderRadius: 22,
      backgroundColor: theme.colors.surfaceAlt,
      borderWidth: 1,
      borderColor: theme.mode === 'dark' ? theme.colors.border : '#FFE0D1',
      paddingHorizontal: 14,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
    },
    headerLocationCopy: {
      flex: 1,
      minWidth: 0,
    },
    headerLocationText: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    headerLocationSubText: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      marginTop: 1,
    },
    headerActions: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      flexShrink: 0,
    },
    headerIconButton: {
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      alignItems: 'center',
      justifyContent: 'center',
      position: 'relative',
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.08,
      shadowRadius: 10,
      shadowOffset: { width: 0, height: 4 },
      elevation: 2,
    },
    cartBadge: {
      position: 'absolute',
      top: 5,
      right: 4,
      minWidth: 17,
      height: 17,
      paddingHorizontal: 4,
      borderRadius: 9,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    cartBadgeText: {
      color: theme.colors.white,
      fontSize: 9,
      fontWeight: '800',
    },
  });
