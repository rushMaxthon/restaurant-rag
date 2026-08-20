import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Animated,
  Easing,
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
  useWindowDimensions,
  type ListRenderItem,
} from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { formatCurrency } from '@services/api';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import { getOfferPalette } from '@/components/offers/offerPalette';
import type { PendingOfferPrompt, PersonalizedOfferCard } from '@/types/app';

interface OfferPromptSheetProps {
  visible: boolean;
  prompt: PendingOfferPrompt | null;
  onApply: (offerId: string) => void;
  onContinue: () => void;
  onDismiss: () => void;
}

function getOfferIconName(offer: PersonalizedOfferCard): string {
  if (offer.discount_type === 'FREE_DELIVERY') {
    return 'bicycle';
  }
  if (offer.discount_type === 'FLAT') {
    return 'cash';
  }
  return 'pricetag-outline';
}

function renderEndsLabel(expiresAt: string | null): string | null {
  if (!expiresAt) {
    return null;
  }
  return `Ends ${new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
  }).format(new Date(expiresAt))}`;
}

function OfferCard({
  offer,
  compact,
  onApply,
}: {
  offer: PersonalizedOfferCard;
  compact: boolean;
  onApply: (offerId: string) => void;
}): React.JSX.Element {
  const theme = useTheme();
  const palette = useMemo(
    () =>
      getOfferPalette(
        {
          offer_type: offer.offer_type,
          audience_type: offer.audience_type,
          cuisine_type: offer.cuisine_type,
          discount_type: offer.discount_type,
        },
        theme.mode,
      ),
    [offer, theme.mode],
  );
  const cardThemeStyle = useMemo(
    () => ({
      backgroundColor: palette.surface,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.58)',
    }),
    [palette.surface],
  );

  return (
    <View
      style={[
        styles.offerCard,
        compact ? styles.offerCardCompact : null,
        cardThemeStyle,
      ]}
    >
      <View
        style={[
          styles.glow,
          compact ? styles.glowCompact : null,
          { backgroundColor: palette.glow },
        ]}
      />
      <View
        style={[
          styles.shape,
          styles.shapePrimary,
          compact ? styles.shapePrimaryCompact : null,
          { backgroundColor: palette.shapePrimary },
        ]}
      />
      <View
        style={[
          styles.shape,
          styles.shapeSecondary,
          compact ? styles.shapeSecondaryCompact : null,
          { backgroundColor: palette.shapeSecondary },
        ]}
      />

      <View style={styles.headerRow}>
        <View style={[styles.badge, { backgroundColor: palette.badgeSurface }]}>
          <Icon color={palette.accent} name="sparkles" size={12} />
          <Text
            numberOfLines={1}
            style={[styles.badgeText, { color: palette.accent }]}
          >
            Offer available
          </Text>
        </View>
        <View
          style={[styles.iconBubble, { backgroundColor: palette.iconSurface }]}
        >
          <Icon
            color={palette.iconText}
            name={getOfferIconName(offer)}
            size={compact ? 15 : 17}
          />
        </View>
      </View>

      <Text
        numberOfLines={compact ? 2 : 3}
        style={[styles.title, compact ? styles.titleCompact : null]}
      >
        {offer.title}
      </Text>
      <Text numberOfLines={1} style={styles.restaurant}>
        {offer.restaurant_name}
      </Text>
      <Text
        numberOfLines={2}
        style={[styles.subtitle, compact ? styles.subtitleCompact : null]}
      >
        {offer.discount_label ??
          offer.subtitle ??
          'Offer available for this order'}
      </Text>

      <View style={styles.metaRow}>
        <View style={styles.metaChip}>
          <Text numberOfLines={1} style={styles.metaChipText}>
            {Number(offer.minimum_order_amount) > 0
              ? `Min ${formatCurrency(offer.minimum_order_amount)}`
              : 'No min order'}
          </Text>
        </View>
        {renderEndsLabel(offer.expires_at) ? (
          <View style={styles.metaChip}>
            <Text numberOfLines={1} style={styles.metaChipText}>
              {renderEndsLabel(offer.expires_at)}
            </Text>
          </View>
        ) : null}
      </View>

      <Pressable
        onPress={() => onApply(offer.offer_id)}
        style={[
          styles.primaryButton,
          compact ? styles.primaryButtonCompact : null,
          { backgroundColor: palette.ctaSurface },
        ]}
      >
        <Text style={[styles.primaryButtonText, { color: palette.ctaText }]}>
          Apply Offer
        </Text>
      </Pressable>
    </View>
  );
}

function SingleOfferCard({
  offer,
  onApply,
  onContinue,
}: {
  offer: PersonalizedOfferCard;
  onApply: (offerId: string) => void;
  onContinue: () => void;
}): React.JSX.Element {
  const theme = useTheme();
  const palette = getOfferPalette(
    {
      offer_type: offer.offer_type,
      audience_type: offer.audience_type,
      cuisine_type: offer.cuisine_type,
      discount_type: offer.discount_type,
    },
    theme.mode,
  );
  const cardThemeStyle = {
    backgroundColor: palette.surface,
    borderColor:
      theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.58)',
  };

  return (
    <View style={[styles.offerCard, styles.singleOfferCard, cardThemeStyle]}>
      <View style={[styles.glow, { backgroundColor: palette.glow }]} />
      <View
        style={[
          styles.shape,
          styles.shapePrimary,
          { backgroundColor: palette.shapePrimary },
        ]}
      />
      <View
        style={[
          styles.shape,
          styles.shapeSecondary,
          { backgroundColor: palette.shapeSecondary },
        ]}
      />

      <View style={styles.headerRow}>
        <View style={[styles.badge, { backgroundColor: palette.badgeSurface }]}>
          <Icon color={palette.accent} name="sparkles" size={12} />
          <Text style={[styles.badgeText, { color: palette.accent }]}>
            Offer available
          </Text>
        </View>
        <View
          style={[styles.iconBubble, { backgroundColor: palette.iconSurface }]}
        >
          <Icon
            color={palette.iconText}
            name={getOfferIconName(offer)}
            size={17}
          />
        </View>
      </View>

      <Text style={styles.title}>{offer.title}</Text>
      <Text style={styles.restaurant}>{offer.restaurant_name}</Text>
      <Text style={styles.subtitle}>
        {offer.discount_label ?? 'Offer available for this order'}
      </Text>

      <View style={styles.metaRow}>
        <View style={styles.metaChip}>
          <Text style={styles.metaChipText}>
            {Number(offer.minimum_order_amount) > 0
              ? `Min ${formatCurrency(offer.minimum_order_amount)}`
              : 'No min order'}
          </Text>
        </View>
        {renderEndsLabel(offer.expires_at) ? (
          <View style={styles.metaChip}>
            <Text style={styles.metaChipText}>
              {renderEndsLabel(offer.expires_at)}
            </Text>
          </View>
        ) : null}
      </View>

      <View style={styles.actions}>
        <Pressable onPress={onContinue} style={styles.actionSecondary}>
          <Text style={styles.secondaryButtonText}>Continue without offer</Text>
        </Pressable>
        <Pressable
          onPress={() => onApply(offer.offer_id)}
          style={[
            styles.actionPrimary,
            { backgroundColor: palette.ctaSurface },
          ]}
        >
          <Text style={[styles.primaryButtonText, { color: palette.ctaText }]}>
            Apply Offer
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

export function OfferPromptSheet({
  visible,
  prompt,
  onApply,
  onContinue,
  onDismiss,
}: OfferPromptSheetProps): React.JSX.Element | null {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const [mounted, setMounted] = useState(visible);
  const backdrop = useRef(new Animated.Value(visible ? 1 : 0)).current;
  const sheet = useRef(new Animated.Value(visible ? 1 : 0)).current;
  const { width } = useWindowDimensions();

  useEffect(() => {
    if (visible) {
      setMounted(true);
    }
    Animated.parallel([
      Animated.timing(backdrop, {
        toValue: visible ? 1 : 0,
        duration: visible ? 180 : 140,
        easing: Easing.out(Easing.ease),
        useNativeDriver: true,
      }),
      Animated.spring(sheet, {
        toValue: visible ? 1 : 0,
        damping: 18,
        mass: 0.9,
        stiffness: 180,
        useNativeDriver: true,
      }),
    ]).start(({ finished }) => {
      if (finished && !visible) {
        setMounted(false);
      }
    });
  }, [backdrop, sheet, visible]);

  const sheetStyle = useMemo(
    () => ({
      opacity: sheet,
      transform: [
        {
          translateY: sheet.interpolate({
            inputRange: [0, 1],
            outputRange: [28, 0],
          }),
        },
      ],
    }),
    [sheet],
  );

  const carouselCardWidth = Math.min(Math.max(width - 72, 268), 352);
  // Hoisted out of the JSX below so the carousel rows are not rebuilt on every
  // render of the sheet.
  const renderOffer = useCallback<ListRenderItem<PersonalizedOfferCard>>(
    ({ item }) => (
      <View style={[styles.carouselItem, { width: carouselCardWidth }]}>
        <OfferCard compact offer={item} onApply={onApply} />
      </View>
    ),
    [carouselCardWidth, onApply, styles],
  );

  if (!mounted || !prompt || prompt.offers.length === 0) {
    return null;
  }

  const multipleOffers = prompt.offers.length > 1;
  const singleOffer = prompt.offers[0];

  if (!multipleOffers) {
    return (
      <Modal
        animationType="none"
        onRequestClose={onDismiss}
        transparent
        visible={mounted}
      >
        <View style={styles.root}>
          <Animated.View style={[styles.backdrop, { opacity: backdrop }]}>
            <Pressable onPress={onDismiss} style={StyleSheet.absoluteFill} />
          </Animated.View>
          <View pointerEvents="box-none" style={styles.bottomWrap}>
            <Animated.View style={sheetStyle}>
              <SingleOfferCard
                offer={singleOffer}
                onApply={onApply}
                onContinue={onContinue}
              />
            </Animated.View>
          </View>
        </View>
      </Modal>
    );
  }

  return (
    <Modal
      animationType="none"
      onRequestClose={onDismiss}
      transparent
      visible={mounted}
    >
      <View style={styles.root}>
        <Animated.View style={[styles.backdrop, { opacity: backdrop }]}>
          <Pressable onPress={onDismiss} style={StyleSheet.absoluteFill} />
        </Animated.View>
        <View pointerEvents="box-none" style={styles.bottomWrap}>
          <Animated.View style={[styles.sheet, sheetStyle]}>
            <Text style={styles.sheetEyebrow}>
              {multipleOffers ? 'Choose your best offer' : 'Offer available'}
            </Text>
            <Text style={styles.sheetHeading}>
              {multipleOffers
                ? `${prompt.offers.length} offers unlocked for this add`
                : 'Apply this offer before adding to cart'}
            </Text>

            {multipleOffers ? (
              <FlatList
                contentContainerStyle={styles.carouselContent}
                data={prompt.offers}
                decelerationRate="fast"
                horizontal
                keyExtractor={item => item.offer_id}
                renderItem={renderOffer}
                showsHorizontalScrollIndicator={false}
                snapToAlignment="start"
                snapToInterval={carouselCardWidth + 12}
              />
            ) : (
              <OfferCard
                compact={false}
                offer={singleOffer}
                onApply={onApply}
              />
            )}

            <Pressable onPress={onContinue} style={styles.secondaryButton}>
              <Text style={styles.secondaryButtonText}>
                Continue without offer
              </Text>
            </Pressable>
          </Animated.View>
        </View>
      </View>
    </Modal>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    root: { flex: 1, justifyContent: 'flex-end' },
    backdrop: {
      ...StyleSheet.absoluteFill,
      backgroundColor: 'rgba(18, 22, 33, 0.34)',
    },
    bottomWrap: { paddingHorizontal: 16, paddingBottom: 18 },
    sheet: {
      borderRadius: 28,
      backgroundColor:
        theme.mode === 'dark' ? theme.colors.surfaceAlt : '#FFF7F2',
      paddingHorizontal: 16,
      paddingTop: 16,
      paddingBottom: 14,
      gap: 12,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.18,
      shadowOffset: { width: 0, height: 18 },
      shadowRadius: 28,
      elevation: 16,
    },
    sheetEyebrow: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '900',
      letterSpacing: 1.2,
      textTransform: 'uppercase',
    },
    sheetHeading: {
      color: theme.colors.text,
      fontSize: 19,
      lineHeight: 24,
      fontWeight: '900',
    },
    carouselContent: { paddingRight: 4 },
    carouselItem: { marginRight: 12 },
    offerCard: {
      overflow: 'hidden',
      borderRadius: 24,
      padding: 18,
      borderWidth: 1,
      gap: 10,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.16,
      shadowOffset: { width: 0, height: 14 },
      shadowRadius: 22,
      elevation: 10,
    },
    singleOfferCard: {
      borderRadius: 26,
    },
    offerCardCompact: {
      minHeight: 236,
      padding: 16,
      gap: 9,
    },
    glow: {
      position: 'absolute',
      width: 126,
      height: 126,
      borderRadius: 63,
      top: -34,
      right: -12,
    },
    glowCompact: {
      width: 112,
      height: 112,
      top: -28,
      right: -18,
    },
    shape: { position: 'absolute', borderRadius: 999 },
    shapePrimary: { width: 108, height: 108, right: -18, bottom: 18 },
    shapePrimaryCompact: { width: 96, height: 96, right: -20, bottom: 16 },
    shapeSecondary: { width: 62, height: 62, left: -16, top: 82 },
    shapeSecondaryCompact: { width: 54, height: 54, left: -18, top: 74 },
    headerRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      zIndex: 1,
    },
    badge: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 5,
      minHeight: 28,
      maxWidth: '82%',
      borderRadius: 14,
      paddingHorizontal: 10,
      borderWidth: 1,
      borderColor: 'rgba(255,255,255,0.34)',
    },
    badgeText: { fontSize: 11, fontWeight: '800' },
    iconBubble: {
      width: 34,
      height: 34,
      borderRadius: 17,
      alignItems: 'center',
      justifyContent: 'center',
    },
    title: {
      zIndex: 1,
      color: theme.colors.text,
      fontSize: 22,
      lineHeight: 27,
      fontWeight: '900',
    },
    titleCompact: { fontSize: 19, lineHeight: 24 },
    restaurant: {
      zIndex: 1,
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '700',
    },
    subtitle: {
      zIndex: 1,
      color: theme.colors.text,
      fontSize: 15,
      lineHeight: 20,
      fontWeight: '700',
    },
    subtitleCompact: { fontSize: 14, lineHeight: 18 },
    metaRow: { zIndex: 1, flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
    metaChip: {
      minHeight: 28,
      borderRadius: 14,
      paddingHorizontal: 10,
      justifyContent: 'center',
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255,255,255,0.42)',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.5)',
    },
    metaChipText: { color: theme.colors.hint, fontSize: 11, fontWeight: '800' },
    primaryButton: {
      zIndex: 1,
      marginTop: 4,
      minHeight: 48,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.5)',
    },
    primaryButtonCompact: {
      minHeight: 44,
    },
    primaryButtonText: { fontSize: 14, fontWeight: '900' },
    secondaryButton: {
      minHeight: 48,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    secondaryButtonText: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    actions: { zIndex: 1, flexDirection: 'row', gap: 10, marginTop: 4 },
    actionSecondary: {
      flex: 1,
      minHeight: 48,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : 'rgba(255,255,255,0.52)',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.56)',
    },
    actionPrimary: {
      minWidth: 124,
      minHeight: 48,
      borderRadius: 16,
      alignItems: 'center',
      justifyContent: 'center',
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : 'rgba(255,255,255,0.5)',
    },
  });

const styles = createStyles(theme);
