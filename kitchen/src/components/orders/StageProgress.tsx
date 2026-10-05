import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import type { FulfillmentType, OrderStatus } from '@/types/app';
import { inkOn } from '@/themePalette';
import { Icon } from '@components/Icon';

const STEPS: { status: OrderStatus; label: (type: FulfillmentType) => string }[] = [
  { status: 'PLACED', label: () => 'New' },
  { status: 'ACCEPTED', label: () => 'Accepted' },
  { status: 'PREPARING', label: () => 'Cooking' },
  { status: 'OUT_FOR_DELIVERY', label: type => (type === 'DELIVERY' ? 'With rider' : 'Ready') },
  { status: 'DELIVERED', label: type => (type === 'DELIVERY' ? 'Delivered' : 'Collected') },
];

// Where this order is in the one linear flow. Done steps are ticked, the
// current one is filled with its stage colour, the rest are outlines.
//
// Every step takes an equal share of the width, and each draws the half of
// the connector on either side of its node — so the whole track fits any
// card from a phone to a tablet pane, with nothing to scroll.
export const StageProgress = ({
  status,
  fulfillment,
}: {
  status: OrderStatus;
  fulfillment: FulfillmentType;
}) => {
  const theme = useTheme();
  const { colors } = theme;
  const currentIndex = STEPS.findIndex(step => step.status === status);
  const reached = (index: number) => currentIndex >= index;
  return (
    <View
      style={styles.row}
      accessible
      accessibilityLabel={`Stage: ${STEPS[currentIndex]?.label(fulfillment) ?? status}`}>
      {STEPS.map((step, index) => {
        const done = currentIndex > index;
        const current = currentIndex === index;
        const stageColor = theme.status[step.status];
        const lineColor = (on: boolean) => (on ? stageColor : colors.border);
        return (
          <View key={step.status} style={styles.step}>
            <View style={styles.track}>
              <View
                style={[
                  styles.line,
                  index === 0 ? styles.lineHidden : { backgroundColor: lineColor(reached(index)) },
                ]}
              />
              <View
                style={[
                  styles.node,
                  current && styles.nodeCurrent,
                  {
                    backgroundColor: current || done ? stageColor : colors.surface,
                    borderColor: current || done ? stageColor : colors.border,
                  },
                ]}>
                {done ? <Icon name="checkmark" size={15} color={inkOn(stageColor)} /> : null}
              </View>
              <View
                style={[
                  styles.line,
                  index === STEPS.length - 1
                    ? styles.lineHidden
                    : { backgroundColor: lineColor(reached(index + 1)) },
                ]}
              />
            </View>
            <Text
              numberOfLines={1}
              adjustsFontSizeToFit
              minimumFontScale={0.8}
              style={[
                styles.label,
                { color: current ? colors.text : colors.textMuted },
                current && styles.labelCurrent,
              ]}>
              {step.label(fulfillment)}
            </Text>
          </View>
        );
      })}
    </View>
  );
};

const styles = StyleSheet.create({
  row: { flexDirection: 'row' },
  step: { flex: 1, alignItems: 'center', gap: 6, minWidth: 0 },
  track: { flexDirection: 'row', alignItems: 'center', alignSelf: 'stretch', height: 32 },
  line: { flex: 1, height: 3 },
  // The outer half-connectors of the first and last step: nothing to join.
  lineHidden: { backgroundColor: 'transparent' },
  node: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  nodeCurrent: { width: 32, height: 32, borderRadius: 16 },
  label: { fontSize: 12, fontWeight: '700', textAlign: 'center', paddingHorizontal: 2 },
  labelCurrent: { fontWeight: '900' },
});
