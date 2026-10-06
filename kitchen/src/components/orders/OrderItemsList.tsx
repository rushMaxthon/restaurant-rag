import React, { memo } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { radius, useTheme } from '@/theme';
import type { OrderLine } from '@/types/app';
import { lineModifiers } from '@utils/board';

interface OrderItemsListProps {
  items: OrderLine[];
  // Detail screens read from further away and have the room.
  large?: boolean;
}

// The dishes on an order, shared by the ticket, the detail screen and the
// completed view, so a finished order reads exactly as it did on the board.
// Quantity sits in a badge in a fixed column: on a busy board it is the first
// thing anybody looks for, and a "2" must never be mistaken for part of a name.
const OrderItemsListComponent = ({ items, large = false }: OrderItemsListProps) => {
  const { colors } = useTheme();
  return (
    <View style={styles.list}>
      {items.map(line => {
        // The size reads with the name ("Butter Pav · Pack of 6"); every
        // other choice keeps its own row beneath.
        const all = lineModifiers(line);
        const size = all.find(row => row.label === 'Size' && !row.half)?.text ?? null;
        const mods = all.filter(row => !(row.label === 'Size' && !row.half));
        const many = line.quantity > 1;
        return (
          <View key={line.id} style={styles.line}>
            <View
              style={[
                styles.qty,
                large && styles.qtyLarge,
                { backgroundColor: many ? colors.text : colors.surfaceMuted },
              ]}>
              <Text
                style={[
                  styles.qtyText,
                  large && styles.qtyTextLarge,
                  { color: many ? colors.surface : colors.text },
                ]}>
                {line.quantity}
              </Text>
            </View>
            <View style={styles.body}>
              <Text style={[styles.name, large && styles.nameLarge, { color: colors.text }]}>
                {line.item_name_snapshot}
                {size ? <Text style={[styles.size, { color: colors.textMuted }]}>{`  ${size}`}</Text> : null}
              </Text>
              {mods.map((row, index) => (
                <View key={index} style={styles.modRow}>
                  {row.label ? (
                    <Text style={[styles.modLabel, { color: colors.textMuted }]}>{row.label}</Text>
                  ) : null}
                  {/* A half is a tag, not a word in a sentence: which side
                      gets the pepperoni is the part a cook must not skim. */}
                  {row.half ? (
                    <View style={[styles.half, { backgroundColor: colors.text }]}>
                      <Text style={[styles.halfText, { color: colors.surface }]}>
                        {row.half === 'LEFT' ? 'LEFT ½' : 'RIGHT ½'}
                      </Text>
                    </View>
                  ) : null}
                  <Text style={[styles.modText, large && styles.modTextLarge, { color: colors.text }]}>
                    {row.text}
                  </Text>
                </View>
              ))}
            </View>
          </View>
        );
      })}
    </View>
  );
};

export const OrderItemsList = memo(OrderItemsListComponent);

const styles = StyleSheet.create({
  list: { gap: 12 },
  line: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' },
  // A doubled-up quantity is filled dark: "2" and "1" must not look alike.
  qty: {
    minWidth: 30,
    height: 30,
    paddingHorizontal: 6,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  qtyLarge: { minWidth: 38, height: 38 },
  qtyText: { fontSize: 16, fontWeight: '900', fontVariant: ['tabular-nums'] },
  qtyTextLarge: { fontSize: 19 },
  body: { flex: 1, gap: 4, paddingTop: 4 },
  name: { fontSize: 16, fontWeight: '800', lineHeight: 21 },
  nameLarge: { fontSize: 19, lineHeight: 25 },
  size: { fontSize: 13, fontWeight: '600' },
  modRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  modLabel: { fontSize: 12, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.4 },
  half: { borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 },
  halfText: { fontSize: 11, fontWeight: '900', letterSpacing: 0.4 },
  modText: { fontSize: 14, lineHeight: 19, fontWeight: '500', flexShrink: 1 },
  modTextLarge: { fontSize: 16, lineHeight: 22 },
});
