import React from 'react';
import { Text, View } from 'react-native';
import { formatCurrency } from '@services/api';
import { useThemedStyles } from '@/theme';
import type {
  AppliedPersonalizedOffer,
  DeliveryQuote,
  OrderCharges,
} from '@/types/app';
import {
  deliveryDistanceNote,
  deliveryFeeNote,
  pendingAmountLabel,
} from '@utils/deliveryQuote';
import { createStyles } from '../styles';

interface CartSummaryCardProps {
  subtotal: number;
  /** Null until the server has priced the trip. Never a local fallback. */
  deliveryFee: number | null;
  /** Everything that is neither food nor delivery. Null until priced. */
  taxAmount: number | null;
  charges: OrderCharges | null;
  deliveryQuote: DeliveryQuote | null;
  quoteLoading: boolean;
  quoteError: string | null;
  isMonetaryPersonalizedOffer: boolean;
  total: number;
  fulfillmentChipLabel: string;
  activePersonalizedOffer: AppliedPersonalizedOffer | null;
  personalizedOfferRowValue: string | null;
}

/**
 * Bill breakdown. Split out of `CartScreen` so it re-renders only when the
 * amounts or the applied offer change.
 *
 * **Every number here arrives priced.** This card used to be handed a delivery
 * fee read off the branch and a tax of `subtotal * 0.05`; it now takes the
 * server's figures or nothing, and says "Worked out at checkout" when it has
 * nothing. A placeholder zero is how this screen came to announce free
 * delivery on an order the courier charged 50 for.
 */
function CartSummaryCardComponent({
  subtotal,
  deliveryFee,
  taxAmount,
  charges,
  deliveryQuote,
  quoteLoading,
  quoteError,
  isMonetaryPersonalizedOffer,
  total,
  fulfillmentChipLabel,
  activePersonalizedOffer,
  personalizedOfferRowValue,
}: CartSummaryCardProps): React.JSX.Element {
  const styles = useThemedStyles(createStyles);

  /** The one string a row shows instead of an amount it does not have. */
  const pending = pendingAmountLabel(quoteLoading, quoteError);
  const distanceNote = deliveryDistanceNote(deliveryQuote);
  const feeNote = deliveryFeeNote(deliveryQuote);

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
        <Text style={styles.summaryValue}>
          {deliveryFee == null ? pending : formatCurrency(deliveryFee)}
        </Text>
      </View>
      {/* How far, and whether a courier actually priced it. A fee with no
          provenance is the one a support call six weeks later cannot explain. */}
      {distanceNote ? (
        <Text style={styles.summarySubtitle}>{distanceNote}</Text>
      ) : null}
      {/* Whose problem it is, when the courier did not price it. Said in words
          rather than left as a number that silently fell back. */}
      {feeNote ? <Text style={styles.summarySubtitle}>{feeNote}</Text> : null}

      <View style={styles.summaryRow}>
        <Text style={styles.summaryLabel}>Taxes and charges</Text>
        <Text style={styles.summaryValue}>
          {taxAmount == null ? pending : formatCurrency(taxAmount)}
        </Text>
      </View>
      {/* Opened rather than collapsed: a phone has no hover and a tap target
          for a disclosure is one more thing to miss, while four short rows
          cost less height than the sheet that would hide them. Each carries
          the server's own sentence — a platform fee with nothing under it
          reads as a made-up number. */}
      {charges?.lines.map((line) => (
        <View key={line.key} style={styles.summaryRow}>
          <Text style={[styles.summaryLabel, styles.summarySubtitle]}>
            {line.label}
          </Text>
          <Text style={[styles.summaryValue, styles.summarySubtitle]}>
            {formatCurrency(line.amount)}
          </Text>
        </View>
      ))}

      {quoteError ? (
        <Text style={styles.summarySubtitle}>
          Delivery and charges are worked out at checkout.
        </Text>
      ) : null}

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
        <Text style={styles.totalLabel}>
          {deliveryFee == null ? 'Food total' : 'Total'}
        </Text>
        <Text style={styles.totalValue}>{formatCurrency(total)}</Text>
      </View>
    </View>
  );
}

export const CartSummaryCard = React.memo(CartSummaryCardComponent);
