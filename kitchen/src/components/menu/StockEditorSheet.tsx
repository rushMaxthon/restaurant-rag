import React, { useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { radius, space, type as typeScale, useTheme } from '@/theme';
import type { DishStockChange, KitchenMenuItem, SizeStockChange } from '@/types/app';
import { Icon } from '@components/Icon';
import { PrimaryButton } from '@components/PrimaryButton';
import { changedCount, countText } from '@utils/menuStock';

interface StockEditorSheetProps {
  item: KitchenMenuItem | null;
  pending: boolean;
  error: string | null;
  onClose: () => void;
  // The quick ±1, saved at once like the list's old counter.
  onStep: (item: KitchenMenuItem, delta: number) => void;
  // Resolves true when every change was saved.
  onSave: (
    item: KitchenMenuItem,
    dish: DishStockChange,
    sizes: { sizeId: string; change: SizeStockChange }[],
  ) => Promise<boolean>;
}

interface Draft {
  outOfStock: boolean;
  count: string;
  daily: string;
  sizes: Record<string, { count: string; daily: string }>;
}

const draftOf = (item: KitchenMenuItem): Draft => ({
  outOfStock: item.out_of_stock,
  count: countText(item.stock_quantity),
  daily: countText(item.stock_daily_quantity),
  sizes: Object.fromEntries(
    item.sizes.map(size => [size.id, { count: countText(size.stock_quantity), daily: countText(size.stock_daily_quantity) }]),
  ),
});

// Everything about one dish's stock, in one sheet. Only boxes that were
// changed are sent: a count moves with every order, and an editor opened at
// 10 and saved after three sold must not put three back on the shelf.
export const StockEditorSheet = ({ item, pending, error, onClose, onStep, onSave }: StockEditorSheetProps) => {
  const { colors } = useTheme();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  // A fresh draft for a different dish. The same dish coming back from the
  // server (after a quick ±1) only refreshes its count box, so anything else
  // typed into the sheet is not thrown away.
  const itemId = item?.id ?? null;
  useEffect(() => {
    setDraft(item ? draftOf(item) : null);
    setProblem(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemId]);
  const liveCount = item?.stock_quantity ?? null;
  useEffect(() => {
    setDraft(current => (current ? { ...current, count: countText(liveCount) } : current));
  }, [liveCount]);

  if (!item || !draft) {
    return null;
  }

  const save = async () => {
    try {
      const dish: DishStockChange = {};
      if (draft.outOfStock !== item.out_of_stock) {
        dish.out_of_stock = draft.outOfStock;
      }
      const count = changedCount(draft.count, item.stock_quantity);
      if (count.changed) {
        dish.stock_quantity = count.value;
      }
      const daily = changedCount(draft.daily, item.stock_daily_quantity);
      if (daily.changed) {
        dish.stock_daily_quantity = daily.value;
      }
      const sizes = item.sizes.flatMap(size => {
        const typed = draft.sizes[size.id];
        const change: SizeStockChange = {};
        const sizeCount = changedCount(typed.count, size.stock_quantity);
        if (sizeCount.changed) {
          change.stock_quantity = sizeCount.value;
        }
        const sizeDaily = changedCount(typed.daily, size.stock_daily_quantity);
        if (sizeDaily.changed) {
          change.stock_daily_quantity = sizeDaily.value;
        }
        return Object.keys(change).length ? [{ sizeId: size.id, change }] : [];
      });
      setProblem(null);
      if (Object.keys(dish).length === 0 && sizes.length === 0) {
        onClose();
        return;
      }
      if (await onSave(item, dish, sizes)) {
        onClose();
      }
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : 'Check the numbers and try again.');
    }
  };

  const field = (
    label: string,
    hint: string,
    value: string,
    onChange: (next: string) => void,
    testID: string,
  ) => (
    <View style={styles.field}>
      <Text style={[styles.label, { color: colors.text }]}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChange}
        keyboardType="number-pad"
        placeholder="Not counted"
        placeholderTextColor={colors.textMuted}
        accessibilityLabel={label}
        style={[styles.input, { color: colors.text, backgroundColor: colors.inputBackground, borderColor: colors.border }]}
      />
      <Text style={[styles.hint, { color: colors.textMuted }]}>{hint}</Text>
    </View>
  );

  return (
    <Modal visible animationType="slide" transparent onRequestClose={onClose}>
      <KeyboardAvoidingView
        style={styles.backdrop}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <Pressable style={styles.scrim} onPress={onClose} accessibilityLabel="Close" />
        <View style={[styles.sheet, { backgroundColor: colors.surface }]}>
          <View style={styles.head}>
            <View style={styles.headText}>
              <Text style={[styles.title, { color: colors.text }]}>{item.name}</Text>
              <Text style={[styles.subtitle, { color: colors.textMuted }]}>
                {item.category} · {item.branch_name}
              </Text>
            </View>
            <Pressable
              testID="stock-editor-close"
              onPress={onClose}
              hitSlop={8}
              accessibilityRole="button"
              accessibilityLabel="Close"
              style={[styles.close, { backgroundColor: colors.surfaceMuted }]}>
              <Icon name="close" size={22} color={colors.text} />
            </Pressable>
          </View>

          <ScrollView contentContainerStyle={styles.body} keyboardShouldPersistTaps="handled">
            {!item.is_available ? (
              <View style={[styles.notice, { backgroundColor: colors.surfaceMuted }]}>
                <Icon name="eye-off-outline" size={18} color={colors.textMuted} />
                <Text style={[styles.noticeText, { color: colors.text }]}>
                  Hidden by the owner: customers cannot see it whatever its stock. Only the owner can show it again.
                </Text>
              </View>
            ) : null}

            <View style={[styles.switchRow, { borderColor: colors.border }]}>
              <View style={styles.headText}>
                <Text style={[styles.label, { color: colors.text }]}>Out of stock</Text>
                <Text style={[styles.hint, { color: colors.textMuted }]}>
                  Stays on the menu, but nobody can order it.
                </Text>
              </View>
              <Switch
                testID="stock-editor-out"
                value={draft.outOfStock}
                onValueChange={outOfStock => setDraft({ ...draft, outOfStock })}
                trackColor={{ true: colors.danger, false: colors.border }}
                accessibilityLabel="Out of stock"
              />
            </View>

            {item.stock_quantity !== null && !item.out_of_stock ? (
              <View style={[styles.quick, { borderColor: colors.border }]}>
                <View style={styles.headText}>
                  <Text style={[styles.label, { color: colors.text }]}>Quick adjust</Text>
                  <Text style={[styles.hint, { color: colors.textMuted }]}>Saved straight away.</Text>
                </View>
                <View style={[styles.stepper, { borderColor: colors.border }]}>
                  <Pressable
                    testID={`menu-minus-${item.id}`}
                    onPress={() => onStep(item, -1)}
                    disabled={pending || item.stock_quantity === 0}
                    accessibilityRole="button"
                    accessibilityLabel={`One fewer ${item.name}`}
                    style={styles.stepButton}>
                    <Icon name="remove" size={22} color={item.stock_quantity === 0 ? colors.border : colors.text} />
                  </Pressable>
                  <Text style={[styles.stepValue, { color: colors.text }]}>{item.stock_quantity}</Text>
                  <Pressable
                    testID={`menu-plus-${item.id}`}
                    onPress={() => onStep(item, 1)}
                    disabled={pending}
                    accessibilityRole="button"
                    accessibilityLabel={`One more ${item.name}`}
                    style={styles.stepButton}>
                    <Icon name="add" size={22} color={colors.text} />
                  </Pressable>
                </View>
              </View>
            ) : null}

            {field(
              'Left now',
              'Goes down with every order. Empty means not counted.',
              draft.count,
              count => setDraft({ ...draft, count }),
              'stock-editor-count',
            )}
            {field(
              'Each morning',
              'The count is set back to this every morning. Empty means you restock by hand.',
              draft.daily,
              daily => setDraft({ ...draft, daily }),
              'stock-editor-daily',
            )}

            {item.sizes.length ? (
              <View style={styles.sizesBlock}>
                <Text style={[styles.sectionTitle, { color: colors.textMuted }]}>Sizes</Text>
                <Text style={[styles.hint, { color: colors.textMuted }]}>
                  A size with its own count sells from it; an empty size uses the dish’s count.
                </Text>
                {item.sizes.map(size => (
                  <View key={size.id} style={[styles.sizeCard, { borderColor: colors.border }]}>
                    <Text style={[styles.sizeName, { color: colors.text }]}>{size.name}</Text>
                    <View style={styles.sizeFields}>
                      <View style={styles.sizeField}>
                        {field(
                          'Left now',
                          '',
                          draft.sizes[size.id].count,
                          count => setDraft({ ...draft, sizes: { ...draft.sizes, [size.id]: { ...draft.sizes[size.id], count } } }),
                          `stock-editor-size-count-${size.id}`,
                        )}
                      </View>
                      <View style={styles.sizeField}>
                        {field(
                          'Each morning',
                          '',
                          draft.sizes[size.id].daily,
                          daily => setDraft({ ...draft, sizes: { ...draft.sizes, [size.id]: { ...draft.sizes[size.id], daily } } }),
                          `stock-editor-size-daily-${size.id}`,
                        )}
                      </View>
                    </View>
                  </View>
                ))}
              </View>
            ) : null}

            {problem || error ? (
              <View accessibilityRole="alert" style={[styles.notice, { backgroundColor: colors.dangerSoft }]}>
                <Icon name="alert-circle" size={18} color={colors.danger} />
                <Text style={[styles.noticeText, { color: colors.danger }]}>{problem ?? error}</Text>
              </View>
            ) : null}
          </ScrollView>

          <View style={[styles.foot, { borderTopColor: colors.border }]}>
            <PrimaryButton testID="stock-editor-save" label="Save stock" onPress={save} loading={pending} />
          </View>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
};

const styles = StyleSheet.create({
  backdrop: { flex: 1, justifyContent: 'flex-end' },
  scrim: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(0,0,0,0.45)' },
  sheet: {
    maxHeight: '90%',
    width: '100%',
    maxWidth: 640,
    alignSelf: 'center',
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    overflow: 'hidden',
  },
  head: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.xl, paddingBottom: space.md },
  headText: { flex: 1, gap: 2 },
  title: typeScale.title,
  subtitle: typeScale.caption,
  close: { width: 44, height: 44, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  body: { paddingHorizontal: space.xl, paddingBottom: space.xl, gap: space.lg },
  notice: { flexDirection: 'row', gap: 10, borderRadius: radius.md, padding: space.md, alignItems: 'flex-start' },
  noticeText: { flex: 1, fontSize: 14, fontWeight: '600', lineHeight: 20 },
  switchRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: space.md,
  },
  quick: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: space.md,
  },
  stepper: { flexDirection: 'row', alignItems: 'center', borderWidth: 1, borderRadius: radius.md },
  stepButton: { width: 48, height: 44, alignItems: 'center', justifyContent: 'center' },
  stepValue: { minWidth: 34, textAlign: 'center', fontSize: 18, fontWeight: '900', fontVariant: ['tabular-nums'] },
  field: { gap: 6 },
  label: { fontSize: 15, fontWeight: '700' },
  input: {
    minHeight: 52,
    borderWidth: 1.5,
    borderRadius: radius.md,
    paddingHorizontal: space.lg,
    fontSize: 18,
    fontWeight: '800',
    fontVariant: ['tabular-nums'],
  },
  hint: { fontSize: 13, lineHeight: 18 },
  sizesBlock: { gap: space.sm },
  sectionTitle: { ...typeScale.overline },
  sizeCard: { borderWidth: 1, borderRadius: radius.md, padding: space.md, gap: space.sm },
  sizeName: { fontSize: 16, fontWeight: '800' },
  sizeFields: { flexDirection: 'row', gap: space.md },
  sizeField: { flex: 1 },
  foot: { padding: space.lg, borderTopWidth: StyleSheet.hairlineWidth },
});
