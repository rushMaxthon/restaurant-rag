import React, { useRef } from 'react';
import {
  StyleSheet,
  TextInput,
  View,
  type TextInputInstance,
} from 'react-native';

import { AppText } from '@components/ui/AppText';
import { useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { font, radius, space, touch } from '@theme/tokens';
import type { Dmy } from '@utils/onboarding';

type Part = keyof Dmy;
type Ref = React.RefObject<TextInputInstance | null>;

/**
 * A date as three boxes, DD / MM / YYYY - no picker library, and no calendar
 * to scroll back eighteen years through for a date of birth. A full box moves
 * on to the next; backspace in an empty box moves back.
 */
export function DateInput({
  label,
  value,
  onChange,
  error,
  editable = true,
}: {
  label: string;
  value: Dmy;
  onChange: (next: Dmy) => void;
  error?: string | null;
  editable?: boolean;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const dd = useRef<TextInputInstance>(null);
  const mm = useRef<TextInputInstance>(null);
  const yyyy = useRef<TextInputInstance>(null);

  const box = (
    part: Part,
    ref: Ref,
    length: number,
    a11y: string,
    next?: Ref,
    prev?: Ref,
  ) => (
    <TextInput
      ref={ref}
      value={value[part]}
      editable={editable}
      accessibilityLabel={`${label}: ${a11y}`}
      onChangeText={raw => {
        const digits = raw.replace(/\D/g, '').slice(0, length);
        onChange({ ...value, [part]: digits });
        if (digits.length === length) next?.current?.focus();
      }}
      onKeyPress={e => {
        if (e.nativeEvent.key === 'Backspace' && !value[part])
          prev?.current?.focus();
      }}
      keyboardType="number-pad"
      maxLength={length}
      placeholder={t(`onboarding.date.${part}`)}
      placeholderTextColor={colors.textFaint}
      selectionColor={colors.primary}
      maxFontSizeMultiplier={1.3}
      style={[
        styles.box,
        part === 'yyyy' ? styles.year : styles.short,
        {
          color: editable ? colors.text : colors.textMuted,
          backgroundColor: colors.surfaceAlt,
          borderColor: error ? colors.danger : colors.border,
        },
      ]}
    />
  );

  return (
    <View>
      <AppText variant="label" tone="muted" style={styles.label}>
        {label}
      </AppText>
      <View style={styles.row}>
        {box('dd', dd, 2, t('onboarding.date.day'), mm)}
        <AppText variant="heading" tone="faint">
          /
        </AppText>
        {box('mm', mm, 2, t('onboarding.date.month'), yyyy, dd)}
        <AppText variant="heading" tone="faint">
          /
        </AppText>
        {box('yyyy', yyyy, 4, t('onboarding.date.year'), undefined, mm)}
      </View>
      {error ? (
        <AppText variant="caption" tone="danger" style={styles.error}>
          {error}
        </AppText>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  label: { marginBottom: space.xs + 2 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  box: {
    minHeight: touch.large,
    borderRadius: radius.lg,
    borderWidth: 1.5,
    textAlign: 'center',
    fontFamily: font.semibold,
    fontSize: 18,
    paddingHorizontal: space.sm,
  },
  // Fixed widths, not flex: inside a row that does not stretch, flex boxes
  // collapsed to slivers on the emulator.
  short: { width: 72 },
  year: { width: 112 },
  error: { marginTop: space.xs },
});
