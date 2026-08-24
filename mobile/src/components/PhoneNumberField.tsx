import React from 'react';
import { StyleSheet, TextInput, View, type TextInputProps } from 'react-native';
import { CountryCodePicker } from '@components/CountryCodePicker';
import type { CountryOption } from '@/data/countries';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

/**
 * Country code and mobile number as one control.
 *
 * The two used to be separate bordered boxes in a `flexWrap: 'wrap'` row, with
 * the number field carrying a `minWidth` sized to its placeholder. That row was
 * only ever one dp from breaking - a 393dp screen left the field 197dp against
 * a 196dp minimum - so any narrower device, or any OS font scale above 100%,
 * pushed the field onto its own line and the pair stopped reading as one input.
 *
 * Drawing a single border around both removes the failure mode rather than
 * re-tuning it. There is no wrap and no width threshold left to cross: the
 * trigger is content-sized and never shrinks, and the number field takes
 * whatever remains. That is why this is responsive at every size - the layout
 * has no breakpoint to get wrong.
 */
type Props = {
  selectedCountry: CountryOption;
  onSelectCountry: (country: CountryOption) => void;
  value: string;
  onChangeText: (value: string) => void;
  hasError?: boolean;
  placeholder?: string;
} & Pick<TextInputProps, 'autoFocus' | 'onSubmitEditing' | 'returnKeyType'>;

export function PhoneNumberField({
  selectedCountry,
  onSelectCountry,
  value,
  onChangeText,
  hasError = false,
  /**
   * Short on purpose. The screens label this field "Mobile number" directly
   * above, so a long placeholder repeated the label and was also the single
   * reason the old layout needed 196dp. "Enter your mobile number" does not fit
   * beside a country chip on a 320dp screen at any font scale.
   */
  placeholder = 'Mobile number',
  ...inputProps
}: Props): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);

  return (
    <View style={[styles.container, hasError ? styles.containerError : null]}>
      <CountryCodePicker
        onSelect={onSelectCountry}
        selectedCountry={selectedCountry}
        variant="embedded"
      />
      <View style={styles.divider} />
      <TextInput
        autoComplete="tel"
        keyboardType="number-pad"
        maxLength={15}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.hint}
        style={styles.input}
        value={value}
        {...inputProps}
      />
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    container: {
      flexDirection: 'row',
      // `stretch`, not `center`: the trigger and divider run the full height of
      // the control, which is what makes the two halves read as one field.
      alignItems: 'stretch',
      // `minHeight` rather than `height` so the control grows with the OS font
      // instead of clipping its own contents at large accessibility sizes.
      minHeight: 50,
      borderRadius: 10,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.background,
      // Keeps the trigger's press highlight and the divider inside the rounded
      // corners.
      overflow: 'hidden',
    },
    containerError: {
      // Matches the `inputError` colour the other auth fields use.
      borderColor: 'rgba(203,32,45,0.35)',
    },
    divider: {
      width: StyleSheet.hairlineWidth,
      backgroundColor: theme.colors.border,
    },
    input: {
      flex: 1,
      // Without this a flex child refuses to shrink below its content width,
      // which is exactly how the old row ended up overflowing and wrapping.
      // With it the field simply takes the space that is left, on any screen.
      minWidth: 0,
      paddingHorizontal: 12,
      color: theme.colors.text,
      fontSize: 15,
    },
  });
