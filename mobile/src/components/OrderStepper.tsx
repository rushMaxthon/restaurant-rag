import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { OrderStatus } from '@/types/app';

const steps: OrderStatus[] = [
  'PLACED',
  'ACCEPTED',
  'PREPARING',
  'OUT_FOR_DELIVERY',
  'DELIVERED',
];

interface OrderStepperProps {
  status: OrderStatus;
}

export function OrderStepper({ status }: OrderStepperProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const activeIndex = steps.indexOf(status);

  // Neither state belongs on the fulfillment rail: an unpaid order has not
  // started, and a cancelled one never will.
  if (status === 'PAYMENT_PENDING' || status === 'CANCELLED') {
    const isPending = status === 'PAYMENT_PENDING';
    return (
      <View
        style={[
          styles.noticeCard,
          isPending ? styles.noticeCardPending : styles.noticeCardCancelled,
        ]}
      >
        <Text style={styles.noticeTitle}>
          {isPending ? 'Waiting for payment' : 'Order cancelled'}
        </Text>
        <Text style={styles.noticeText}>
          {isPending
            ? 'The restaurant starts preparing this order as soon as the payment is confirmed.'
            : 'This order was cancelled and will not be prepared.'}
        </Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {steps.map((step, index) => {
        const done = index < activeIndex;
        const active = index === activeIndex;
        const pending = index > activeIndex;
        return (
          <View key={step} style={styles.row}>
            <View style={styles.rail}>
              {index > 0 ? (
                <View
                  style={[
                    styles.connector,
                    styles.connectorTop,
                    done || active ? styles.connectorActive : null,
                  ]}
                />
              ) : null}
              {index < steps.length - 1 ? (
                <View
                  style={[
                    styles.connector,
                    styles.connectorBottom,
                    done ? styles.connectorActive : null,
                  ]}
                />
              ) : null}
              <View
                style={[
                  styles.dot,
                  done
                    ? styles.dotDone
                    : active
                    ? styles.dotActive
                    : styles.dotPending,
                ]}
              >
                {done ? <Text style={styles.doneText}>✓</Text> : null}
                {active ? <View style={styles.dotInner} /> : null}
              </View>
            </View>
            <View
              style={[
                styles.copy,
                active ? styles.copyActive : null,
                pending ? styles.copyPending : null,
              ]}
            >
              <Text
                style={[
                  styles.title,
                  active ? styles.titleActive : null,
                  pending ? styles.titlePending : null,
                ]}
              >
                {step.replaceAll('_', ' ')}
              </Text>
              <Text style={styles.subtitle}>
                {done ? 'Completed' : active ? 'In progress' : 'Pending'}
              </Text>
            </View>
          </View>
        );
      })}
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    container: {
      gap: 10,
    },
    noticeCard: {
      borderRadius: 16,
      borderWidth: 1,
      padding: 14,
      gap: 5,
    },
    noticeCardPending: {
      borderColor:
        theme.mode === 'dark' ? theme.colors.border : theme.primaryTint(0.18),
      backgroundColor:
        theme.mode === 'dark'
          ? theme.colors.surfaceAlt
          : theme.colors.primarySoft,
    },
    noticeCardCancelled: {
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.card,
    },
    noticeTitle: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    noticeText: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 17,
    },
    row: {
      flexDirection: 'row',
      gap: 12,
      alignItems: 'stretch',
    },
    rail: {
      width: 28,
      alignItems: 'center',
      position: 'relative',
    },
    connector: {
      position: 'absolute',
      width: 2,
      left: 13,
      backgroundColor: theme.colors.border,
    },
    connectorTop: {
      top: 0,
      bottom: '50%',
      marginBottom: 14,
    },
    connectorBottom: {
      top: '50%',
      bottom: 0,
      marginTop: 14,
    },
    connectorActive: {
      backgroundColor: theme.colors.primary,
    },
    dot: {
      width: 28,
      height: 28,
      borderRadius: 14,
      alignItems: 'center',
      justifyContent: 'center',
      marginTop: 2,
    },
    dotDone: {
      backgroundColor: theme.colors.success,
    },
    dotActive: {
      backgroundColor: theme.primaryTint(0.12),
      borderWidth: 1,
      borderColor: theme.primaryTint(0.18),
    },
    dotPending: {
      borderWidth: 2,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
    },
    dotInner: {
      width: 12,
      height: 12,
      borderRadius: 6,
      backgroundColor: theme.colors.primary,
    },
    doneText: {
      color: theme.colors.white,
      fontWeight: '800',
      fontSize: 12,
    },
    copy: {
      flex: 1,
      borderRadius: 16,
      paddingVertical: 4,
    },
    copyActive: {
      paddingHorizontal: 10,
      backgroundColor: theme.colors.primarySoft,
    },
    copyPending: {
      opacity: 0.78,
    },
    title: {
      color: theme.colors.text,
      fontWeight: '700',
      fontSize: 14,
    },
    titleActive: {
      color: theme.colors.primary,
    },
    titlePending: {
      color: theme.colors.secondaryText,
    },
    subtitle: {
      color: theme.colors.hint,
      fontSize: 12,
      marginTop: 2,
    },
  });

