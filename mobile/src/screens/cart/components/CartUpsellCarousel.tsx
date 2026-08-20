import React, { useCallback } from 'react';
import {
  FlatList,
  Text,
  View,
  type ListRenderItem,
  type ViewToken,
} from 'react-native';
import { formatCurrency } from '@services/api';
import { useThemedStyles } from '@/theme';
import type { ComboUpsellSuggestion } from '@/types/app';
import { createStyles } from '../styles';
import { ComboAddButton } from './ComboAddButton';

interface CartUpsellCarouselProps {
  upsellSuggestions: ComboUpsellSuggestion[];
  upsellCardWidth: number;
  revealedUpsellComboIds: Set<string>;
  interactedUpsellComboIds: Set<string>;
  visibleUpsellComboIds: Set<string>;
  viewabilityConfig: object;
  onViewableItemsChanged: (info: {
    viewableItems: ViewToken[];
    changed: ViewToken[];
  }) => void;
  onAddCombo: (suggestion: ComboUpsellSuggestion) => void;
}

/**
 * The "complete your combo" carousel inside the items panel.
 *
 * Split out of `CartScreen` so that editing the notes field or expanding the
 * order details no longer re-renders the carousel or its cards.
 */
function CartUpsellCarouselComponent({
  upsellSuggestions,
  upsellCardWidth,
  revealedUpsellComboIds,
  interactedUpsellComboIds,
  visibleUpsellComboIds,
  viewabilityConfig,
  onViewableItemsChanged,
  onAddCombo,
}: CartUpsellCarouselProps): React.JSX.Element | null {
  const styles = useThemedStyles(createStyles);

  const renderUpsellSuggestion = useCallback<
    ListRenderItem<ComboUpsellSuggestion>
  >(
    ({ item: suggestion }) => {
      const missingNames = suggestion.missing_items.map(item => item.name);
      const previewNames =
        missingNames.length > 2
          ? `${missingNames.slice(0, 2).join(', ')} +${missingNames.length - 2}`
          : missingNames.join(', ');

      return (
        <View style={[styles.upsellCarouselCard, { width: upsellCardWidth }]}>
          <View style={styles.upsellCarouselGlow} />
          <View style={styles.upsellCarouselHeader}>
            <View style={styles.upsellBadge}>
              <Text style={styles.upsellBadgeText}>Combo pick</Text>
            </View>
            <Text style={styles.upsellPrice}>
              {formatCurrency(suggestion.suggested_combo_price)}
            </Text>
          </View>
          <Text numberOfLines={2} style={styles.upsellCarouselTitle}>
            {suggestion.combo_name}
          </Text>
          <Text numberOfLines={2} style={styles.upsellCarouselText}>
            Frequently ordered with your cart. Add {previewNames}.
          </Text>
          <View style={styles.upsellFooter}>
            <View style={styles.upsellFooterCopy}>
              <Text numberOfLines={1} style={styles.upsellFooterLabel}>
                Missing items
              </Text>
              <Text numberOfLines={1} style={styles.upsellFooterItems}>
                {missingNames.join(', ')}
              </Text>
            </View>
            <ComboAddButton
              hasAppeared={revealedUpsellComboIds.has(suggestion.combo_id)}
              interacted={interactedUpsellComboIds.has(suggestion.combo_id)}
              isVisible={visibleUpsellComboIds.has(suggestion.combo_id)}
              label={suggestion.missing_items.length > 1 ? 'Add items' : 'Add'}
              onPress={() => onAddCombo(suggestion)}
            />
          </View>
        </View>
      );
    },
    [
      interactedUpsellComboIds,
      onAddCombo,
      revealedUpsellComboIds,
      styles,
      upsellCardWidth,
      visibleUpsellComboIds,
    ],
  );

  const renderSeparator = useCallback(
    () => <View style={styles.upsellCarouselSpacer} />,
    [styles],
  );

  if (upsellSuggestions.length === 0) {
    return null;
  }

  return (
    <View style={styles.upsellSection}>
      <View style={styles.upsellSectionHeader}>
        <Text style={styles.upsellSectionTitle}>Complete your combo</Text>
      </View>
      <Text style={styles.upsellSectionMeta}>Frequently ordered together</Text>
      <FlatList
        horizontal
        data={upsellSuggestions}
        keyExtractor={item => item.combo_id}
        renderItem={renderUpsellSuggestion}
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.upsellCarouselContent}
        ItemSeparatorComponent={renderSeparator}
        onViewableItemsChanged={onViewableItemsChanged}
        snapToAlignment="start"
        snapToInterval={upsellCardWidth + 12}
        decelerationRate="fast"
        disableIntervalMomentum
        viewabilityConfig={viewabilityConfig}
      />
    </View>
  );
}

export const CartUpsellCarousel = React.memo(CartUpsellCarouselComponent);
