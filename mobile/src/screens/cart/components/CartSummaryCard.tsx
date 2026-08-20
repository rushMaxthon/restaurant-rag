import React from 'react';
import { Text, View } from 'react-native';
import { formatCurrency } from '@services/api';
import { useThemedStyles } from '@/theme';
import type { AppliedPersonalizedOffer } from '@/types/app';
import { createStyles } from '../styles';

interface CartSummaryCardProps {
  subtotal: number;
  deliveryFee: number;
  taxAmount: number;
  isMonetaryPersonalizedOffer: boolean;
  total: number;
  fulfillmentChipLabel: string;
  activePersonalizedOffer: AppliedPersonalizedOffer | null;
  personalizedOfferRowValue: string | null;
}

/**
 * Bill breakdown. Split out of `CartScreen` so it re-renders only when the
 * amounts or the applied offer change.
 */
function CartSummaryCardComponent({
  subtotal,
  deliveryFee,
  taxAmount,
  isMonetaryPersonalizedOffer,
  total,
  fulfillmentChipLabel,
  activePersonalizedOffer,
  personalizedOfferRowValue,
}: CartSummaryCardProps): React.JSX.Element {
  const styles = useThemedStyles(createStyles);

  return (
    <View style={styles.summaryCard}>
      <View style={styles.summaryHeader}>
        <View>
          <Text style={styles.summaryTitle}>Bill details</Text>
          <Text style={styles.summarySubtitle}>
            A clean breakdown before you pay
          </Text>
        </View>
        <Text style={styles.summaryBadge}>Live total</Text>
      </View>
      <View style={styles.summaryRow}>
        <Text style={styles.summaryLabel}>Fulfillment</Text>
        <Text style={styles.summaryValue}>{fulfillmentChipLabel}</Text>
      </View>
      <View style={styles.summaryRow}>
        <Text style={styles.summaryLabel}>Subtotal</Text>
        <Text style={styles.summaryValue}>{formatCurrency(subtotal)}</Text>
      </View>
      <View style={styles.summaryRow}>
        <Text style={styles.summaryLabel}>Delivery fee</Text>
        <Text style={styles.summaryValue}>{formatCurrency(deliveryFee)}</Text>
      </View>
      <View style={styles.summaryRow}>
        <Text style={styles.summaryLabel}>Tax</Text>
        <Text style={styles.summaryValue}>{formatCurrency(taxAmount)}</Text>
      </View>
      {activePersonalizedOffer && isMonetaryPersonalizedOffer ? (
        <View style={styles.summaryRow}>
          <Text style={[styles.summaryLabel, styles.summaryDiscountLabel]}>
            {activePersonalizedOffer.discountLabel ?? 'Offer discount'}
          </Text>
          <Text style={[styles.summaryValue, styles.summaryDiscountValue]}>
            {personalizedOfferRowValue}
          </Text>
        </View>
      ) : null}
      <View style={styles.summaryDivider} />
      <View style={styles.summaryRow}>
        <Text style={styles.totalLabel}>Total</Text>
        <Text style={styles.totalValue}>{formatCurrency(total)}</Text>
      </View>
    </View>
  );
}

export const CartSummaryCard = React.memo(CartSummaryCardComponent);
