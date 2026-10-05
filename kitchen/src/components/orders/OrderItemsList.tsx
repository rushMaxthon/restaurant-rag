import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import type { OrderLine } from '@/types/app';
import { lineModifiers } from '@utils/board';

interface OrderItemsListProps {
  items: OrderLine[];
  // Detail screens read from further away and have the room.
  large?: boolean;
}

// The dishes on an order, shared by the ticket, the detail screen and the
// completed view, so a finished order reads exactly as it did on the board.
// Quantity is the heaviest thing here and always in the same column, because
// on a busy board it is the first thing anybody looks for.
export const OrderItemsList = ({ items, large = false }: OrderItemsListProps) => {
  const { colors } = useTheme();
  return (
    <View style={styles.list}>
      {items.map(line => {
        const mods = lineModifiers(line);
        return (
          <View key={line.id} style={styles.line}>
            <Text style={[styles.qty, large && styles.qtyLarge, { color: colors.text }]}>
              {line.quantity}×
            </Text>
            <View style={styles.body}>
              <Text style={[styles.name, large && styles.nameLarge, { color: colors.text }]}>
                {line.item_name_snapshot}
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
                  <Text
                    style={[styles.modText, large && styles.modTextLarge, { color: colors.text }]}>
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

const styles = StyleSheet.create({
  list: { gap: 10 },
  line: { flexDirection: 'row', gap: 10 },
  qty: { width: 34, fontSize: 18, fontWeight: '900' },
  qtyLarge: { width: 44, fontSize: 22 },
  body: { flex: 1, gap: 3 },
  name: { fontSize: 16, fontWeight: '700', lineHeight: 21 },
  nameLarge: { fontSize: 19, lineHeight: 25 },
  modRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  modLabel: { fontSize: 13, fontWeight: '700' },
  half: { borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 },
  halfText: { fontSize: 11, fontWeight: '900', letterSpacing: 0.4 },
  modText: { fontSize: 14, lineHeight: 19, flexShrink: 1 },
  modTextLarge: { fontSize: 16, lineHeight: 22 },
});
