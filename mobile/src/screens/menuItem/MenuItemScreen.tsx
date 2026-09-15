import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  Animated,
  Image,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import {
  SafeAreaView,
  useSafeAreaInsets,
} from 'react-native-safe-area-context';
import { useNavigation, useRoute } from '@react-navigation/native';
import type { RouteProp } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import Icon from 'react-native-vector-icons/Ionicons';
import { FavoriteIconButton } from '@components/FavoriteIconButton';
import { SkeletonBlock } from '@components/SkeletonBlock';
import {
  useAppActions,
  useCart,
  useFavoritesState,
  useSession,
} from '@hooks/useAppStore';
import type { RootStackParamList } from '@/navigation/AppNavigator';
import {
  ApiError,
  api,
  formatCurrency,
  placeholderImage,
  toNumber,
} from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type {
  CartSelectedOption,
  MenuItem,
  MenuItemCustomizationGroup,
  MenuItemCustomizationOption,
  MenuItemPortion,
  Restaurant,
} from '@/types/app';
import { checkAuthAndRedirect } from '@utils/authRedirect';
import { getNewItemBadgeMeta } from '@utils/newItemBadges';
import {
  buildLineItemId,
  calculateUnitPrice,
  chargedExtraPrice,
  findCustomizationOption,
  formatCustomizationSummary,
  getActiveCustomizationGroups,
  getDefaultSelectedSize,
  getSideCounts,
  groupSupportsHalves,
  nextSideFor,
  portionOf,
  regroupForMode,
  roomOnSide,
  splitSummary,
  validateCustomizationSelection,
} from '@/utils/menuItemCustomization';

type MenuItemDetailRoute = RouteProp<RootStackParamList, 'MenuItemDetail'>;

// ─── Collapsible Group ──────────────────────────────────────────────────────

function CollapsibleGroup({
  group,
  groupSelections,
  selectedOptions,
  isSplit,
  onOptionPress,
  onOptionQuantityChange,
  onSetSplit,
  onSetOptionPortion,
  styles,
  theme,
}: {
  group: MenuItemCustomizationGroup;
  groupSelections: CartSelectedOption[];
  selectedOptions: CartSelectedOption[];
  /** Whether the customer has put this group into half-and-half mode. */
  isSplit: boolean;
  onOptionPress: (
    group: MenuItemCustomizationGroup,
    option: MenuItemCustomizationOption,
  ) => void;
  onOptionQuantityChange: (optionId: string, delta: number) => void;
  onSetSplit: (group: MenuItemCustomizationGroup, wantSplit: boolean) => void;
  onSetOptionPortion: (
    group: MenuItemCustomizationGroup,
    optionId: string,
    portion: MenuItemPortion,
  ) => void;
  styles: ReturnType<typeof createStyles>;
  theme: AppTheme;
}) {
  const [open, setOpen] = useState(group.is_required);
  const rotateAnim = useRef(
    new Animated.Value(group.is_required ? 1 : 0),
  ).current;
  const heightAnim = useRef(
    new Animated.Value(group.is_required ? 1 : 0),
  ).current;

  const toggle = () => {
    const toValue = open ? 0 : 1;
    Animated.parallel([
      Animated.spring(rotateAnim, {
        toValue,
        useNativeDriver: true,
        tension: 120,
        friction: 10,
      }),
      Animated.timing(heightAnim, {
        toValue,
        duration: 220,
        useNativeDriver: false,
      }),
    ]).start();
    setOpen(v => !v);
  };

  const chevronRotate = rotateAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '180deg'],
  });

  const selectedCount = groupSelections.length;
  // The owner's flag is what offers the control at all; the customer's switch
  // is what turns it on.
  const canSplit = groupSupportsHalves(group);
  const sideCounts = getSideCounts(groupSelections);

  return (
    <View style={styles.selectionCard}>
      {/* Header — always visible */}
      <Pressable onPress={toggle} style={styles.selectionHeaderPressable}>
        <View style={styles.selectionTitleWrap}>
          <View style={styles.selectionTitleRow}>
            <Text style={styles.selectionTitle}>{group.title}</Text>
            <View
              style={[
                styles.groupStatusChip,
                group.is_required
                  ? styles.groupStatusChipRequired
                  : styles.groupStatusChipOptional,
              ]}
            >
              <Text
                style={[
                  styles.groupStatusChipText,
                  group.is_required
                    ? styles.groupStatusChipTextRequired
                    : styles.groupStatusChipTextOptional,
                ]}
              >
                {group.is_required ? 'Required' : 'Optional'}
              </Text>
            </View>
          </View>
          <Text style={styles.selectionSubtitle}>
            {group.selection_type === 'SINGLE'
              ? 'Single choice'
              : `Pick ${group.min_selection}–${group.max_selection}`}
            {isSplit
              ? ` on each half • ${sideCounts.LEFT} left, ${sideCounts.RIGHT} right`
              : selectedCount > 0
              ? ` • ${selectedCount} selected`
              : ''}
          </Text>
        </View>

        <Animated.Text
          style={[styles.chevron, { transform: [{ rotate: chevronRotate }] }]}
        >
          ^
        </Animated.Text>
      </Pressable>

      {/* Collapsed preview pills */}
      {!open && selectedCount > 0 ? (
        <View style={styles.selectionPreviewRow}>
          {groupSelections.map(sel => {
            const portion = portionOf(sel);
            return (
              <View key={sel.optionId} style={styles.selectionPreviewPill}>
                <Text style={styles.selectionPreviewText}>
                  {portion === 'WHOLE'
                    ? sel.optionName
                    : `${sel.optionName} · ${
                        portion === 'LEFT' ? 'left' : 'right'
                      }`}
                </Text>
              </View>
            );
          })}
        </View>
      ) : null}

      {/* The owner's flag turned into one question, asked once: the same on
          all of it, or different on each half. Asking it per topping produced
          dead ends — two toppings on the whole item and neither could move to
          a half, because each read the other as whole. */}
      {open && canSplit ? (
        <View
          style={styles.splitSwitch}
          accessibilityRole="radiogroup"
          accessibilityLabel={`How to put on ${group.title}`}
        >
          <Pressable
            onPress={() => onSetSplit(group, false)}
            accessibilityRole="radio"
            accessibilityState={{ selected: !isSplit }}
            style={[
              styles.splitSwitchOption,
              !isSplit ? styles.splitSwitchOptionActive : null,
            ]}
          >
            <Text
              style={[
                styles.splitSwitchText,
                !isSplit ? styles.splitSwitchTextActive : null,
              ]}
            >
              Same all over
            </Text>
          </Pressable>
          <Pressable
            onPress={() => onSetSplit(group, true)}
            accessibilityRole="radio"
            accessibilityState={{ selected: isSplit }}
            style={[
              styles.splitSwitchOption,
              isSplit ? styles.splitSwitchOptionActive : null,
            ]}
          >
            <Text
              style={[
                styles.splitSwitchText,
                isSplit ? styles.splitSwitchTextActive : null,
              ]}
            >
              Half &amp; half
            </Text>
          </Pressable>
        </View>
      ) : null}

      {/* Expandable options */}
      {open ? (
        <View style={styles.optionList}>
          {group.options
            .filter(option => option.is_active)
            .map(option => {
              const selection = groupSelections.find(
                entry => entry.optionId === option.id,
              );
              const selected = Boolean(selection);
              const portion = selection ? portionOf(selection) : 'WHOLE';
              const onHalf = isSplit && portion !== 'WHOLE';
              // The side this tap would actually put it on, so the row and the
              // press cannot disagree about where it lands.
              const landsOn = isSplit
                ? nextSideFor(group, groupSelections)
                : 'WHOLE';
              // At the ceiling the ones already chosen stay tappable so they
              // can be taken off again; the rest go quiet. Checking the cap
              // only at Add let someone build an item the kitchen would refuse
              // and told them so at the end.
              const atCeiling =
                !selected && isSplit && !roomOnSide(group, sideCounts, landsOn);
              return (
                <View key={option.id}>
                  <Pressable
                    onPress={() => onOptionPress(group, option)}
                    disabled={atCeiling}
                    style={[
                      styles.optionCard,
                      selected ? styles.optionCardActive : null,
                      atCeiling ? styles.optionCardDisabled : null,
                    ]}
                  >
                    {/* Indicator */}
                    <View
                      style={[
                        styles.optionIndicator,
                        group.selection_type === 'SINGLE'
                          ? styles.optionIndicatorRadio
                          : styles.optionIndicatorCheck,
                        selected ? styles.optionIndicatorActive : null,
                      ]}
                    >
                      {selected ? (
                        <Text style={styles.optionIndicatorMark}>
                          {group.selection_type === 'SINGLE' ? '●' : '✓'}
                        </Text>
                      ) : null}
                    </View>

                    {/* Copy */}
                    <View style={styles.optionCopy}>
                      <Text style={styles.optionName}>{option.name}</Text>
                      {/* {option.is_countable ? (
                      <Text style={styles.optionHint}>Qty adjustable</Text>
                    ) : null} */}
                    </View>

                    {/* Price */}
                    <Text
                      style={[
                        styles.optionPrice,
                        selected ? styles.optionPriceActive : null,
                      ]}
                    >
                      {/* Half the topping, half the price — shown on the row so
                        the number moves when the customer splits it, rather
                        than only in the total. */}
                      {toNumber(option.extra_price) > 0
                        ? `+${formatCurrency(
                            chargedExtraPrice(
                              group,
                              option.extra_price,
                              onHalf ? portion : 'WHOLE',
                            ),
                          )}`
                        : 'Free'}
                    </Text>

                    {/* Countable stepper */}
                    {option.is_countable && selected ? (
                      <View style={styles.optionStepper}>
                        <Pressable
                          onPress={() => onOptionQuantityChange(option.id, -1)}
                          style={styles.optionStepperButton}
                        >
                          <Text style={styles.optionStepperButtonText}>−</Text>
                        </Pressable>
                        <Text style={styles.optionStepperCount}>
                          {selection?.quantity ?? 1}
                        </Text>
                        <Pressable
                          onPress={() => onOptionQuantityChange(option.id, 1)}
                          style={styles.optionStepperButton}
                        >
                          <Text style={styles.optionStepperButtonText}>+</Text>
                        </Pressable>
                      </View>
                    ) : null}
                  </Pressable>

                  {/* Which half, once the group is being split. "Whole" is not
                    offered here: that is the other answer to the question
                    asked above, not a third option beside the two halves. */}
                  {selected && isSplit ? (
                    <View
                      style={styles.portionPicker}
                      accessibilityRole="radiogroup"
                      accessibilityLabel={`Which half for ${option.name}`}
                    >
                      {(['LEFT', 'RIGHT'] as MenuItemPortion[]).map(value => {
                        // Room on the side it would move TO, not counting where
                        // it sits now.
                        const others = groupSelections.filter(
                          entry => entry.optionId !== option.id,
                        );
                        const full =
                          portion !== value &&
                          !roomOnSide(group, getSideCounts(others), value);
                        return (
                          <Pressable
                            key={value}
                            disabled={full}
                            accessibilityRole="radio"
                            accessibilityState={{ selected: portion === value }}
                            onPress={() =>
                              onSetOptionPortion(group, option.id, value)
                            }
                            style={[
                              styles.portionOption,
                              portion === value
                                ? styles.portionOptionActive
                                : null,
                              full ? styles.portionOptionDisabled : null,
                            ]}
                          >
                            <Text
                              style={[
                                styles.portionOptionText,
                                portion === value
                                  ? styles.portionOptionTextActive
                                  : null,
                              ]}
                            >
                              {value === 'LEFT' ? 'Left' : 'Right'}
                            </Text>
                          </Pressable>
                        );
                      })}
                    </View>
                  ) : null}
                </View>
              );
            })}
        </View>
      ) : null}
    </View>
  );
}

// ─── Main Screen ────────────────────────────────────────────────────────────

export function MenuItemDetailScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const insets = useSafeAreaInsets();
  const route = useRoute<MenuItemDetailRoute>();
  const navigation =
    useNavigation<NativeStackNavigationProp<RootStackParamList>>();
  const { token } = useSession();
  const { favoritesHydrated } = useFavoritesState();
  const cart = useCart();
  const {
    addToCart,
    isFavorite,
    isFavoritePending,
    pushToast,
    requestAddToCart,
    toggleFavorite,
    updateCartQuantity,
  } = useAppActions();
  const [item, setItem] = useState<MenuItem | null>(null);
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedSize, setSelectedSize] = useState<{
    id: string;
    name: string;
    price: number | string;
  } | null>(null);
  const [selectedOptions, setSelectedOptions] = useState<CartSelectedOption[]>(
    [],
  );
  // Which splittable groups the customer has put into half-and-half mode. A
  // group is one thing or the other — all of it, or two halves — and this is
  // where that is decided once, rather than inferred from each topping.
  const [splitGroups, setSplitGroups] = useState<Record<string, boolean>>({});
  // How many of this configuration the footer will add; the cart keeps its own
  // count, so this resets to 1 whenever the item changes.
  const [draftQuantity, setDraftQuantity] = useState(1);
  const fade = useRef(new Animated.Value(0)).current;
  const itemId = route.params.itemId;
  // Callers that already know the restaurant pass it through, which lets both
  // requests start together instead of chaining on the item response.
  const routeRestaurantId = route.params.restaurantId ?? null;

  // Distinct lines in the cart, not the quantity of any one of them, so the
  // badge does not track this item's stepper.
  const cartItemCount = cart.items.length;

  const handleOpenCart = useCallback(() => {
    if (
      !checkAuthAndRedirect({
        token,
        navigation,
        pushToast,
        redirectTo: { screen: 'Cart' },
      })
    )
      return;
    navigation.navigate('Cart');
  }, [navigation, pushToast, token]);

  useEffect(() => {
    navigation.setOptions({
      title: item?.name ?? 'Menu item',
      headerRight: () => (
        <Pressable
          hitSlop={10}
          onPress={handleOpenCart}
          style={styles.headerCartButton}
        >
          <Icon color={theme.colors.text} name="bag-handle-outline" size={19} />
          {cartItemCount > 0 ? (
            <View style={styles.headerCartBadge}>
              <Text style={styles.headerCartBadgeText}>
                {cartItemCount > 9 ? '9+' : cartItemCount}
              </Text>
            </View>
          ) : null}
        </Pressable>
      ),
    });
  }, [
    cartItemCount,
    handleOpenCart,
    item?.name,
    navigation,
    styles,
    theme.colors.text,
  ]);

  useEffect(() => {
    let active = true;

    async function loadDetail() {
      setLoading(true);
      setError(null);
      setNotFound(false);
      setItem(null);
      setRestaurant(null);
      setDraftQuantity(1);
      fade.setValue(0);

      try {
        const knownRestaurantRequest = routeRestaurantId
          ? api.getRestaurant(routeRestaurantId, token).catch(() => null)
          : null;

        const menuItem = await api.getMenuItem(itemId, token);
        if (!active) return;
        setItem(menuItem);

        try {
          const restaurantRow =
            knownRestaurantRequest &&
            routeRestaurantId === menuItem.restaurant_id
              ? await knownRestaurantRequest
              : await api.getRestaurant(menuItem.restaurant_id, token);
          if (active) setRestaurant(restaurantRow);
        } catch {
          if (active) setRestaurant(null);
        }

        Animated.timing(fade, {
          toValue: 1,
          duration: 220,
          useNativeDriver: true,
        }).start();
      } catch (nextError) {
        if (!active) return;
        if (nextError instanceof ApiError && nextError.status === 404) {
          setNotFound(true);
        } else {
          setError(
            nextError instanceof Error
              ? nextError.message
              : 'Unable to load this item.',
          );
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    loadDetail();
    return () => {
      active = false;
    };
  }, [fade, itemId, reloadKey, routeRestaurantId, token]);

  useEffect(() => {
    if (!item) {
      setSelectedSize(null);
      setSelectedOptions([]);
      return;
    }
    setSelectedSize(getDefaultSelectedSize(item));
    setSelectedOptions([]);
    setSplitGroups({});
  }, [item]);

  const activeGroups = useMemo(
    () =>
      item ? getActiveCustomizationGroups(item, selectedSize?.id ?? null) : [],
    [item, selectedSize?.id],
  );
  const currentLineItemId = useMemo(
    () =>
      item
        ? buildLineItemId({
            menuItemId: item.id,
            selectedSizeId: selectedSize?.id ?? null,
            selectedOptions,
          })
        : null,
    [item, selectedOptions, selectedSize?.id],
  );
  const currentCartEntry = useMemo(
    () =>
      currentLineItemId
        ? cart.items.find(entry => entry.id === currentLineItemId) ?? null
        : null,
    [cart.items, currentLineItemId],
  );
  const quantity = currentCartEntry?.quantity ?? 0;
  const isInCart = quantity > 0;

  // While a configuration is in the cart the stepper reads the cart line, so
  // the draft is parked at 1 and ready if that line is later removed.
  useEffect(() => {
    if (isInCart) {
      setDraftQuantity(1);
    }
  }, [isInCart]);
  const liveUnitPrice = useMemo(
    () =>
      item
        ? calculateUnitPrice({ menuItem: item, selectedSize, selectedOptions })
        : 0,
    [item, selectedOptions, selectedSize],
  );
  const customizationSummary = useMemo(
    () => formatCustomizationSummary(selectedSize, selectedOptions),
    [selectedOptions, selectedSize],
  );
  const halves = useMemo(
    () => splitSummary(selectedOptions),
    [selectedOptions],
  );
  // Once this configuration is in the cart the stepper edits the cart line
  // itself, so the footer count is the cart count — never a second copy of it.
  const footerQuantity = isInCart ? quantity : draftQuantity;
  const footerTotalPrice = liveUnitPrice * footerQuantity;

  const handleDecreaseQuantity = () => {
    if (isInCart) {
      if (currentLineItemId && quantity > 1) {
        updateCartQuantity(currentLineItemId, quantity - 1);
      }
      return;
    }
    setDraftQuantity(current => Math.max(1, current - 1));
  };

  const handleIncreaseQuantity = () => {
    if (isInCart) {
      if (currentLineItemId) {
        updateCartQuantity(currentLineItemId, quantity + 1);
      }
      return;
    }
    setDraftQuantity(current => current + 1);
  };
  // The size and customization notes that used to sit in the summary column,
  // folded into one line now that the total owns the right-hand side.
  const selectionSummaryLine = useMemo(() => {
    if (!item) {
      return null;
    }
    const parts: string[] = [];
    if (selectedSize) {
      parts.push(`${selectedSize.name} Size`);
    } else if (item.has_sizes) {
      parts.push('Select a size');
    }
    if (customizationSummary.length > 0) {
      parts.push(...customizationSummary);
    } else if (item.has_sizes && !selectedSize) {
      parts.push('Required before add to cart');
    }
    return parts.length > 0 ? parts.join(' • ') : null;
  }, [customizationSummary, item, selectedSize]);

  const upsertOption = (
    group: MenuItemCustomizationGroup,
    option: MenuItemCustomizationOption,
    quantityValue: number,
    portion: MenuItemPortion = 'WHOLE',
  ) => {
    setSelectedOptions(current => {
      const next = current.filter(entry => entry.optionId !== option.id);
      next.push({
        groupId: group.id,
        groupTitle: group.title,
        selectionType: group.selection_type,
        optionId: option.id,
        optionName: option.name,
        extraPrice: option.extra_price,
        quantity: quantityValue,
        isCountable: option.is_countable,
        portion,
      });
      return next;
    });
  };

  const removeOption = (optionId: string) => {
    setSelectedOptions(current =>
      current.filter(entry => entry.optionId !== optionId),
    );
  };

  const handleSizeSelect = (sizeId: string) => {
    if (!item) return;
    const nextSize = item.sizes.find(
      size => size.id === sizeId && size.is_active,
    );
    if (!nextSize) return;
    setSelectedSize({
      id: nextSize.id,
      name: nextSize.name,
      price: nextSize.price,
    });
    setSelectedOptions([]);
    // The groups themselves change with the size, so the modes chosen against
    // the old set have nothing left to describe.
    setSplitGroups({});
  };

  const handleOptionPress = (
    group: MenuItemCustomizationGroup,
    option: MenuItemCustomizationOption,
  ) => {
    const existing = selectedOptions.find(
      entry => entry.optionId === option.id,
    );
    if (group.selection_type === 'SINGLE') {
      const sameSelection = existing != null;
      if (sameSelection && !group.is_required) {
        setSelectedOptions(current =>
          current.filter(entry => entry.groupId !== group.id),
        );
        return;
      }
      setSelectedOptions(current => {
        const next = current.filter(entry => entry.groupId !== group.id);
        next.push({
          groupId: group.id,
          groupTitle: group.title,
          selectionType: group.selection_type,
          optionId: option.id,
          optionName: option.name,
          extraPrice: option.extra_price,
          quantity: 1,
          isCountable: option.is_countable,
        });
        return next;
      });
      return;
    }

    if (existing) {
      removeOption(option.id);
      return;
    }

    const groupSelections = selectedOptions.filter(
      entry => entry.groupId === group.id,
    );

    // Split groups count the owner's maximum on EACH half, so what is already
    // on the side this would land on decides whether it fits — counting the
    // pair together sold one topping per side under a cap of two.
    if (isGroupInSplitMode(group)) {
      const side = nextSideFor(group, groupSelections);
      if (!roomOnSide(group, getSideCounts(groupSelections), side)) {
        pushToast(
          'Selection limit reached',
          `Each half takes up to ${group.max_selection} from ${group.title}.`,
          'info',
        );
        return;
      }
      upsertOption(group, option, 1, side);
      return;
    }

    if (groupSelections.length >= group.max_selection) {
      pushToast(
        'Selection limit reached',
        `${group.title} allows up to ${group.max_selection} choices.`,
        'info',
      );
      return;
    }
    upsertOption(group, option, 1);
  };

  /**
   * Whether this group is currently being split.
   *
   * The customer's switch decides, and only for a group the owner allows to be
   * split at all — a stale mode on a group whose flag was turned off must not
   * keep sending halves the kitchen can no longer make.
   */
  const isGroupInSplitMode = (group: MenuItemCustomizationGroup): boolean =>
    groupSupportsHalves(group) && Boolean(splitGroups[group.id]);

  /**
   * Switch a group between "same all over" and "half & half".
   *
   * The choices are re-rationed for the mode being entered rather than carried
   * across unchanged: two toppings picked for opposite halves are not two
   * toppings on the whole item, and treating them as such put a group over its
   * own limit the moment the customer switched back.
   */
  const handleSetGroupSplit = (
    group: MenuItemCustomizationGroup,
    wantSplit: boolean,
  ) => {
    const groupSelections = selectedOptions.filter(
      entry => entry.groupId === group.id,
    );
    const regrouped = regroupForMode(group, groupSelections, wantSplit);
    setSplitGroups(current => ({ ...current, [group.id]: wantSplit }));
    setSelectedOptions(current => [
      ...current.filter(entry => entry.groupId !== group.id),
      ...regrouped,
    ]);
  };

  /** Move one already-chosen option to the other half. */
  const handleSetOptionPortion = (
    group: MenuItemCustomizationGroup,
    optionId: string,
    portion: MenuItemPortion,
  ) => {
    const others = selectedOptions.filter(
      entry => entry.groupId === group.id && entry.optionId !== optionId,
    );
    if (!roomOnSide(group, getSideCounts(others), portion)) {
      pushToast(
        'Selection limit reached',
        `That half already has ${group.max_selection} from ${group.title}.`,
        'info',
      );
      return;
    }
    setSelectedOptions(current =>
      current.map(entry =>
        entry.optionId === optionId ? { ...entry, portion } : entry,
      ),
    );
  };

  const handleOptionQuantityChange = (optionId: string, delta: number) => {
    if (!item) return;
    const resolved = findCustomizationOption(
      item,
      selectedSize?.id ?? null,
      optionId,
    );
    if (!resolved) return;
    const existing = selectedOptions.find(entry => entry.optionId === optionId);
    if (!existing) {
      if (delta > 0) upsertOption(resolved.group, resolved.option, 1);
      return;
    }
    if (!existing.isCountable) return;
    const nextQuantity = existing.quantity + delta;
    if (nextQuantity <= 0) {
      removeOption(optionId);
      return;
    }
    upsertOption(resolved.group, resolved.option, nextQuantity);
  };

  // ── Loading / Error / Not Found states (unchanged) ──────────────────────

  if (loading) {
    return (
      <SafeAreaView edges={[]} style={styles.screen}>
        <ScrollView contentContainerStyle={styles.content}>
          <SkeletonBlock height={220} />
          <SkeletonBlock height={30} width="68%" />
          <SkeletonBlock height={22} width="30%" />
          <SkeletonBlock height={16} />
          <SkeletonBlock height={16} width="88%" />
          <SkeletonBlock height={118} />
        </ScrollView>
      </SafeAreaView>
    );
  }

  if (notFound) {
    return (
      <SafeAreaView edges={[]} style={styles.screen}>
        <View style={styles.stateCard}>
          <Text style={styles.stateTitle}>
            This item is no longer available.
          </Text>
          <Text style={styles.stateText}>
            It may have sold out or been removed from the menu.
          </Text>
          <Pressable
            onPress={() => navigation.goBack()}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonText}>Back to menu</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  if (error || !item) {
    return (
      <SafeAreaView edges={[]} style={styles.screen}>
        <View style={styles.stateCard}>
          <Text style={styles.stateTitle}>We couldn't load this item.</Text>
          <Text style={styles.stateText}>
            {error ?? 'Please try again shortly.'}
          </Text>
          <View style={styles.stateActions}>
            <Pressable
              onPress={() => setReloadKey(v => v + 1)}
              style={styles.primaryButton}
            >
              <Text style={styles.primaryButtonText}>Retry</Text>
            </Pressable>
            <Pressable
              onPress={() => navigation.goBack()}
              style={styles.secondaryButton}
            >
              <Text style={styles.secondaryButtonText}>Go back</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  // ── Action handlers ──────────────────────────────────────────────────────

  const restaurantName = restaurant?.name ?? 'Restaurant';
  const newItemMeta = getNewItemBadgeMeta(item);
  const displayPrice = item.has_sizes ? item.price : liveUnitPrice;

  const handleAdd = () => {
    if (
      !checkAuthAndRedirect({
        token,
        navigation,
        pushToast,
        redirectTo: {
          screen: 'MenuItemDetail',
          params: {
            itemId: item.id,
            restaurantId: item.restaurant_id,
            restaurantName,
          },
        },
      })
    )
      return;
    const validationError = validateCustomizationSelection({
      menuItem: item,
      selectedSize,
      selectedOptions,
    });
    if (validationError) {
      pushToast('Complete your selection', validationError, 'info');
      return;
    }
    console.log('[MenuItem] add to cart customization payload:', {
      menuItemId: item.id,
      menuItemName: item.name,
      selectedSize,
      selectedOptions,
      unitPrice: liveUnitPrice,
    });
    void requestAddToCart(item, item.restaurant_id, restaurantName, {
      quantity: draftQuantity,
      selectedSize,
      selectedOptions,
      unitPrice: liveUnitPrice,
    });
  };

  const handleToggleFavorite = () => {
    if (
      !checkAuthAndRedirect({
        token,
        navigation,
        pushToast,
        redirectTo: {
          screen: 'MenuItemDetail',
          params: {
            itemId: item.id,
            restaurantId: item.restaurant_id,
            restaurantName,
          },
        },
      })
    )
      return;
    void toggleFavorite({ menuItemId: item.id })
      .then(nextFavorite => {
        pushToast(
          nextFavorite ? 'Saved to favorites' : 'Removed from favorites',
          nextFavorite
            ? `${item.name} is now in your favorites.`
            : `${item.name} was removed from favorites.`,
          'success',
        );
      })
      .catch(nextError => {
        if (
          nextError instanceof ApiError &&
          (nextError.status === 401 || nextError.status === 403)
        ) {
          navigation.navigate('Login', {
            redirectTo: {
              screen: 'MenuItemDetail',
              params: {
                itemId: item.id,
                restaurantId: item.restaurant_id,
                restaurantName,
              },
            },
          });
        }
        pushToast(
          'Favorites unavailable',
          nextError instanceof Error
            ? nextError.message
            : 'Unable to update favorites right now.',
          'error',
        );
      });
  };

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    // FIX: use flex column so actionBar sits below ScrollView — no absolute overlap
    <SafeAreaView edges={[]} style={styles.screen}>
      <Animated.View style={[styles.screenBody, { opacity: fade }]}>
        {/* ── Scrollable content ── */}
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          {/* Hero image — UNCHANGED */}
          <Image
            source={{ uri: item.image_url ?? placeholderImage(item.name) }}
            style={styles.heroImage}
          />

          {/* ── Hero info block ── */}
          <View style={styles.heroContent}>
            <View style={styles.heroTopRow}>
              <View style={styles.restaurantBlock}>
                <Text style={styles.eyebrow}>{restaurantName}</Text>
                <View style={styles.inlineMetaRow}>
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
                  <Text style={styles.categoryLabel}>{item.category}</Text>
                  {newItemMeta.label ? (
                    <View style={styles.badgeNew}>
                      <Text style={styles.badgeNewText}>
                        {newItemMeta.label}
                      </Text>
                    </View>
                  ) : null}
                  {!item.is_available ? (
                    <View style={styles.badgeMuted}>
                      <Text style={styles.badgeMutedText}>Out of stock</Text>
                    </View>
                  ) : null}
                </View>
              </View>
              <FavoriteIconButton
                active={
                  favoritesHydrated ? isFavorite(item.id) : item.is_favorite
                }
                disabled={isFavoritePending(item.id)}
                onPress={handleToggleFavorite}
              />
            </View>

            <Text style={styles.title}>{item.name}</Text>

            <View style={styles.heroMetaRow}>
              <View style={styles.prepChip}>
                <Text style={styles.prepChipIcon}>⏱</Text>
                <Text style={styles.prepChipText}>18–24 min</Text>
              </View>
              {item.is_bestseller ? (
                <View style={styles.bestSellerChip}>
                  <Text style={styles.bestSellerChipText}>Best Seller</Text>
                </View>
              ) : null}
            </View>

            <Text style={styles.description}>
              {item.description ??
                'Freshly prepared with bold flavor, balanced seasoning, and a satisfying finish.'}
            </Text>

            {/* ── Redesigned price row ── */}
            <View style={styles.priceRow}>
              <Text style={styles.priceValue}>
                {item.has_sizes
                  ? `From ${formatCurrency(displayPrice)}`
                  : formatCurrency(displayPrice)}
              </Text>
              {item.has_sizes ? (
                <Text style={styles.priceCaption}>
                  Final price depends on size
                </Text>
              ) : null}
            </View>
          </View>

          {/* ── Size selector — redesigned as horizontal cards ── */}
          {item.has_sizes && item.sizes.length > 0 ? (
            <View style={styles.selectionCard}>
              <View style={styles.selectionHeaderStatic}>
                <View style={styles.selectionTitleRow}>
                  <Text style={styles.selectionTitle}>Choose a size</Text>
                  <View style={styles.groupStatusChipRequired}>
                    <Text style={styles.groupStatusChipTextRequired}>
                      Required
                    </Text>
                  </View>
                </View>
                <Text style={styles.selectionSubtitle}>
                  Base price varies with portion
                </Text>
              </View>

              <View style={styles.sizeCardRow}>
                {item.sizes
                  .filter(size => size.is_active)
                  .map(size => {
                    const selected = selectedSize?.id === size.id;
                    return (
                      <Pressable
                        key={size.id}
                        onPress={() => handleSizeSelect(size.id)}
                        style={[
                          styles.sizeCard,
                          selected ? styles.sizeCardActive : null,
                        ]}
                      >
                        <Text
                          style={[
                            styles.sizeCardLabel,
                            selected ? styles.sizeCardLabelActive : null,
                          ]}
                        >
                          {size.name}
                        </Text>
                        <Text
                          style={[
                            styles.sizeCardPrice,
                            selected ? styles.sizeCardPriceActive : null,
                          ]}
                        >
                          {formatCurrency(size.price)}
                        </Text>
                      </Pressable>
                    );
                  })}
              </View>
            </View>
          ) : null}

          {/* ── Customization groups — collapsible ── */}
          {activeGroups.map(group => {
            const groupSelections = selectedOptions.filter(
              entry => entry.groupId === group.id,
            );
            return (
              <CollapsibleGroup
                key={group.id}
                group={group}
                groupSelections={groupSelections}
                selectedOptions={selectedOptions}
                isSplit={isGroupInSplitMode(group)}
                onOptionPress={handleOptionPress}
                onOptionQuantityChange={handleOptionQuantityChange}
                onSetSplit={handleSetGroupSplit}
                onSetOptionPortion={handleSetOptionPortion}
                styles={styles}
                theme={theme}
              />
            );
          })}

          {/* The item read back as two halves, so it can be checked before
              paying rather than discovered at the door. */}
          {halves.left.length > 0 || halves.right.length > 0 ? (
            <View style={styles.halfSummary}>
              <Text style={styles.halfSummaryTitle}>How it is split</Text>
              <View style={styles.halfSummaryRow}>
                <Text style={styles.halfSummaryLabel}>Left half</Text>
                <Text style={styles.halfSummaryValue}>
                  {halves.left.length > 0
                    ? halves.left.join(', ')
                    : 'Nothing extra'}
                </Text>
              </View>
              <View style={styles.halfSummaryRow}>
                <Text style={styles.halfSummaryLabel}>Right half</Text>
                <Text style={styles.halfSummaryValue}>
                  {halves.right.length > 0
                    ? halves.right.join(', ')
                    : 'Nothing extra'}
                </Text>
              </View>
              {halves.whole.length > 0 ? (
                <View style={styles.halfSummaryRow}>
                  <Text style={styles.halfSummaryLabel}>Whole</Text>
                  <Text style={styles.halfSummaryValue}>
                    {halves.whole.join(', ')}
                  </Text>
                </View>
              ) : null}
            </View>
          ) : null}
        </ScrollView>

        {/* ── Action bar — FIXED: no absolute, sits at bottom of flex column ── */}
        <View
          style={[
            styles.actionBar,
            {
              paddingBottom: Math.max(insets.bottom, 8),
            },
          ]}
        >
          {/* Summary row: quantity picker on the left, running total on the right */}
          <View style={styles.actionSummaryRow}>
            <View style={styles.stepper}>
              <Pressable
                disabled={footerQuantity <= 1}
                onPress={handleDecreaseQuantity}
                style={[
                  styles.stepperButton,
                  footerQuantity <= 1 ? styles.stepperButtonDisabled : null,
                ]}
              >
                <Text
                  style={[
                    styles.stepperButtonText,
                    footerQuantity <= 1
                      ? styles.stepperButtonTextDisabled
                      : null,
                  ]}
                >
                  −
                </Text>
              </Pressable>
              <Text style={styles.stepperCount}>{footerQuantity}</Text>
              <Pressable
                disabled={!item.is_available}
                onPress={handleIncreaseQuantity}
                style={[
                  styles.stepperButton,
                  !item.is_available ? styles.stepperButtonDisabled : null,
                ]}
              >
                <Text
                  style={[
                    styles.stepperButtonText,
                    !item.is_available
                      ? styles.stepperButtonTextDisabled
                      : null,
                  ]}
                >
                  +
                </Text>
              </Pressable>
            </View>

            <View style={styles.actionSummarySecondary}>
              <Text style={styles.actionCaption}>
                {isInCart ? 'Total in cart' : 'Total'}
              </Text>
              <Text style={styles.actionAmount}>
                {formatCurrency(footerTotalPrice)}
              </Text>
            </View>
          </View>

          {selectionSummaryLine ? (
            <Text numberOfLines={1} style={styles.actionSelectionSummary}>
              {selectionSummaryLine}
            </Text>
          ) : null}

          {/* CTA row — once this configuration is in the cart the button
              becomes the way back to it rather than a second add. */}
          <View style={styles.actionControls}>
            <Pressable
              disabled={!isInCart && !item.is_available}
              onPress={isInCart ? handleOpenCart : handleAdd}
              style={[
                styles.addCta,
                !isInCart && !item.is_available ? styles.addCtaDisabled : null,
              ]}
            >
              <Text
                style={[
                  styles.addCtaText,
                  !isInCart && !item.is_available
                    ? styles.addCtaTextDisabled
                    : null,
                ]}
              >
                {isInCart
                  ? 'View Cart'
                  : item.is_available
                  ? `Add to cart • ${formatCurrency(footerTotalPrice)}`
                  : 'Out of stock'}
              </Text>
            </Pressable>
          </View>
        </View>
      </Animated.View>
    </SafeAreaView>
  );
}

// ─── Styles ─────────────────────────────────────────────────────────────────

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    // ── Layout ──────────────────────────────────────────────────────────────
    screen: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    headerCartButton: {
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
    headerCartBadge: {
      position: 'absolute',
      top: 3,
      right: 2,
      minWidth: 16,
      height: 16,
      paddingHorizontal: 4,
      borderRadius: 8,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    headerCartBadgeText: {
      color: theme.colors.white,
      fontSize: 9,
      fontWeight: '800',
    },
    // KEY FIX: flex column so ScrollView + actionBar stack naturally, no overlap
    screenBody: {
      flex: 1,
      flexDirection: 'column',
    },
    content: {
      padding: theme.spacing.screen,
      paddingTop: theme.spacing.stackTop,
      paddingBottom: 10,
      gap: 10,
    },

    // ── Hero (unchanged) ────────────────────────────────────────────────────
    heroImage: {
      width: '100%',
      height: 228,
      borderRadius: 22,
      backgroundColor: theme.colors.card,
    },
    heroContent: {
      gap: 10,
    },
    heroTopRow: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      justifyContent: 'space-between',
      gap: 12,
    },
    restaurantBlock: {
      flex: 1,
      gap: 6,
    },
    inlineMetaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      flexWrap: 'wrap',
      gap: 8,
    },
    foodDot: {
      width: 10,
      height: 10,
      borderRadius: 5,
    },
    categoryLabel: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
      letterSpacing: 0.2,
    },
    badgeNew: {
      paddingHorizontal: 8,
      paddingVertical: 4,
      borderRadius: 999,
      backgroundColor: theme.primaryTint(0.12),
      borderWidth: 1,
      borderColor: theme.primaryTint(0.16),
    },
    badgeNewText: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '700',
    },
    badgeMuted: {
      paddingHorizontal: 8,
      paddingVertical: 4,
      borderRadius: 999,
      backgroundColor: theme.colors.surface,
    },
    badgeMutedText: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      fontWeight: '700',
    },
    eyebrow: {
      color: theme.colors.primary,
      fontSize: 10,
      fontWeight: '800',
      letterSpacing: 0.9,
      textTransform: 'uppercase',
    },
    title: {
      color: theme.colors.text,
      fontSize: 31,
      lineHeight: 33,
      fontWeight: '800',
      letterSpacing: -0.95,
    },
    heroMetaRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
      flexWrap: 'wrap',
    },
    prepChip: {
      minHeight: 30,
      paddingHorizontal: 10,
      borderRadius: 999,
      backgroundColor: theme.colors.surfaceAlt,
      borderWidth: 1,
      borderColor: theme.colors.border,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
    },
    prepChipIcon: { color: theme.colors.primary, fontSize: 12 },
    prepChipText: { color: theme.colors.text, fontSize: 12, fontWeight: '700' },
    bestSellerChip: {
      minHeight: 30,
      paddingHorizontal: 10,
      borderRadius: 999,
      backgroundColor: theme.colors.successSoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    bestSellerChipText: {
      color: theme.colors.offer,
      fontSize: 12,
      fontWeight: '800',
    },
    description: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 21,
    },

    // ── Price row ────────────────────────────────────────────────────────────
    priceRow: { gap: 2 },
    priceValue: {
      color: theme.colors.text,
      fontSize: 24,
      fontWeight: '800',
      letterSpacing: -0.55,
    },
    priceCaption: {
      color: theme.colors.hint,
      fontSize: 12,
      lineHeight: 18,
    },

    // ── Selection card shell ─────────────────────────────────────────────────
    selectionCard: {
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 14,
      gap: 12,
    },

    // Header used by static sections (size)
    selectionHeaderStatic: {
      gap: 3,
    },
    // Header used by collapsible groups (pressable row)
    selectionHeaderPressable: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 10,
    },
    selectionTitleWrap: {
      flex: 1,
      gap: 4,
    },
    selectionTitleRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    },
    selectionTitle: {
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '800',
    },
    selectionSubtitle: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      lineHeight: 16,
    },

    // Chevron for collapsible
    chevron: {
      color: theme.colors.hint,
      fontSize: 22,
      fontWeight: '700',
      lineHeight: 24,
      transform: [{ rotate: '90deg' }],
    },

    // ── Half & half ───────────────────────────────────────────────────────────
    splitSwitch: {
      flexDirection: 'row',
      gap: 6,
      padding: 4,
      borderRadius: 999,
      backgroundColor: theme.colors.surfaceAlt,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    splitSwitchOption: {
      flex: 1,
      paddingVertical: 8,
      borderRadius: 999,
      alignItems: 'center',
    },
    splitSwitchOptionActive: {
      backgroundColor: theme.colors.primarySoft,
    },
    splitSwitchText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
    },
    splitSwitchTextActive: {
      color: theme.colors.primary,
    },
    portionPicker: {
      flexDirection: 'row',
      gap: 8,
      marginTop: 6,
      marginBottom: 2,
      paddingLeft: 36,
    },
    portionOption: {
      paddingHorizontal: 14,
      paddingVertical: 6,
      borderRadius: 999,
      borderWidth: 1.5,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceAlt,
    },
    portionOptionActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    portionOptionDisabled: {
      opacity: 0.4,
    },
    portionOptionText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
    },
    portionOptionTextActive: {
      color: theme.colors.primary,
    },
    optionCardDisabled: {
      opacity: 0.4,
    },
    halfSummary: {
      marginTop: 16,
      padding: 14,
      borderRadius: 14,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceAlt,
      gap: 8,
    },
    halfSummaryTitle: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
    },
    halfSummaryRow: {
      flexDirection: 'row',
      gap: 10,
      alignItems: 'flex-start',
    },
    halfSummaryLabel: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
      width: 78,
    },
    halfSummaryValue: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 12,
      fontWeight: '600',
    },

    // Collapsed selection preview pills
    selectionPreviewRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 6,
    },
    selectionPreviewPill: {
      paddingHorizontal: 10,
      paddingVertical: 4,
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
    },
    selectionPreviewText: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '700',
    },

    // ── Size cards ────────────────────────────────────────────────────────────
    sizeCardRow: {
      flexDirection: 'row',
      flexWrap: 'wrap',
      gap: 8,
    },
    sizeCard: {
      flex: 1,
      minWidth: 80,
      paddingHorizontal: 12,
      paddingVertical: 12,
      borderRadius: 14,
      borderWidth: 1.5,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceAlt,
      alignItems: 'center',
      gap: 4,
    },
    sizeCardActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    sizeCardDot: {
      width: 8,
      height: 8,
      borderRadius: 4,
      backgroundColor: theme.colors.primary,
    },
    sizeCardLabel: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
      textAlign: 'center',
    },
    sizeCardLabelActive: {
      color: theme.colors.primary,
    },
    sizeCardPrice: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
    },
    sizeCardPriceActive: {
      color: theme.colors.primary,
    },

    // ── Status chips ─────────────────────────────────────────────────────────
    groupStatusChip: {
      paddingHorizontal: 8,
      paddingVertical: 3,
      borderRadius: 999,
    },
    groupStatusChipRequired: {
      paddingHorizontal: 8,
      paddingVertical: 3,
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
    },
    groupStatusChipOptional: {
      paddingHorizontal: 8,
      paddingVertical: 3,
      borderRadius: 999,
      backgroundColor: theme.colors.surfaceAlt,
    },
    groupStatusChipText: {
      fontSize: 11,
      fontWeight: '700',
    },
    groupStatusChipTextRequired: {
      color: theme.colors.primary,
      fontSize: 11,
      fontWeight: '700',
    },
    groupStatusChipTextOptional: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      fontWeight: '700',
    },

    // ── Option list ───────────────────────────────────────────────────────────
    optionList: { gap: 8 },
    optionCard: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      borderRadius: 14,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceAlt,
      paddingHorizontal: 12,
      paddingVertical: 11,
    },
    optionCardActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    optionIndicator: {
      width: 18,
      height: 18,
      borderWidth: 2,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      alignItems: 'center',
      justifyContent: 'center',
    },
    optionIndicatorRadio: { borderRadius: 9 },
    optionIndicatorCheck: { borderRadius: 5 },
    optionIndicatorActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primary,
    },
    optionIndicatorMark: {
      color: theme.colors.white,
      fontSize: 9,
      fontWeight: '800',
      lineHeight: 10,
    },
    optionCopy: { flex: 1, gap: 2 },
    optionName: { color: theme.colors.text, fontSize: 13, fontWeight: '700' },
    optionHint: { color: theme.colors.hint, fontSize: 11 },
    optionPrice: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
    },
    optionPriceActive: { color: theme.colors.primary },
    optionStepper: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 6,
      paddingLeft: 4,
    },
    optionStepperButton: {
      width: 26,
      height: 26,
      borderRadius: 13,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    optionStepperButtonText: {
      color: theme.colors.primary,
      fontSize: 14,
      fontWeight: '800',
    },
    optionStepperCount: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '800',
      minWidth: 18,
      textAlign: 'center',
    },

    // ── Action bar — NO absolute positioning ─────────────────────────────────
    // Sits at the bottom of the flex column naturally; scroll content has no
    // bottom padding hack needed.
    actionBar: {
      borderTopWidth: 1,
      borderTopColor: theme.colors.border,
      borderTopLeftRadius: 22,
      borderTopRightRadius: 22,
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceRaised
          : theme.colors.background,
      paddingHorizontal: theme.spacing.screen,
      paddingTop: 10,
      gap: 8,
      shadowColor: '#000',
      shadowOpacity: theme.mode === 'dark' ? 0.28 : 0.08,
      shadowRadius: 14,
      shadowOffset: { width: 0, height: -6 },
      elevation: 12,
    },
    actionSummaryRow: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    actionSummarySecondary: {
      minWidth: 0,
      alignItems: 'flex-end',
      gap: 1,
    },
    actionCaption: {
      color: theme.colors.hint,
      fontSize: 10,
      fontWeight: '700',
      textTransform: 'uppercase',
      letterSpacing: 0.8,
    },
    actionAmount: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '800',
      letterSpacing: -0.45,
    },
    actionSelectionSummary: {
      color: theme.colors.secondaryText,
      fontSize: 11,
      lineHeight: 16,
    },
    actionControls: { gap: 8 },
    addCta: {
      height: 48,
      borderRadius: 14,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      shadowColor: theme.colors.primary,
      shadowOpacity: theme.mode === 'dark' ? 0.32 : 0.18,
      shadowRadius: 12,
      shadowOffset: { width: 0, height: 6 },
      elevation: 4,
    },
    addCtaDisabled: {
      backgroundColor: theme.colors.card,
      borderWidth: 1,
      borderColor: theme.colors.border,
      shadowOpacity: 0,
      elevation: 0,
    },
    addCtaText: { color: theme.colors.white, fontSize: 15, fontWeight: '800' },
    addCtaTextDisabled: { color: theme.colors.hint },
    stepper: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
      paddingHorizontal: 12,
      paddingVertical: 8,
      borderRadius: 999,
      backgroundColor: theme.colors.primarySoft,
    },
    stepperButton: {
      width: 30,
      height: 30,
      borderRadius: 15,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
    },
    stepperButtonDisabled: { backgroundColor: theme.colors.card },
    stepperButtonText: {
      color: theme.colors.primary,
      fontSize: 18,
      fontWeight: '800',
    },
    stepperButtonTextDisabled: { color: theme.colors.hint },
    stepperCount: { color: theme.colors.text, fontSize: 15, fontWeight: '800' },

    // ── Error / not-found states ─────────────────────────────────────────────
    stateCard: {
      flex: 1,
      margin: theme.spacing.screen,
      marginTop: theme.spacing.stackTop,
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 20,
      gap: 12,
      alignItems: 'flex-start',
      justifyContent: 'center',
    },
    stateTitle: { color: theme.colors.text, fontSize: 20, fontWeight: '800' },
    stateText: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      lineHeight: 22,
    },
    stateActions: { flexDirection: 'row', gap: 10, flexWrap: 'wrap' },
    primaryButton: {
      minHeight: 46,
      paddingHorizontal: 16,
      borderRadius: 14,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
    },
    primaryButtonText: {
      color: theme.colors.white,
      fontSize: 14,
      fontWeight: '800',
    },
    secondaryButton: {
      minHeight: 46,
      paddingHorizontal: 16,
      borderRadius: 14,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.primaryTint(0.18),
    },
    secondaryButtonText: {
      color: theme.colors.primary,
      fontSize: 14,
      fontWeight: '800',
    },
  });
