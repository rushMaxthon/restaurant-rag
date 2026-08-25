import React, {
  forwardRef,
  useCallback,
  useEffect,
  useRef,
  useState,
  type PropsWithChildren,
  type ReactNode,
} from 'react';
import {
  Animated,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

/**
 * The label / control / message stack every field on the auth screens shares.
 *
 * The message slot holds either the error or the helper text, never both: they
 * occupy the same line, so showing both would push the form down by a row the
 * moment validation fails and make the whole screen jump.
 */
type AuthFieldProps = PropsWithChildren<{
  label: string;
  error?: string;
  helperText?: string;
}>;

export function AuthField({
  label,
  error,
  helperText,
  children,
}: AuthFieldProps): React.JSX.Element {
  const styles = useThemedStyles(createStyles);
  const message = error ?? helperText;

  return (
    <View style={styles.field}>
      <Text style={styles.label}>{label}</Text>
      {children}
      {message ? (
        <Text style={error ? styles.errorText : styles.helperText}>
          {message}
        </Text>
      ) : null}
    </View>
  );
}

type AuthTextFieldProps = AuthFieldProps & {
  value: string;
  onChangeText: (value: string) => void;
  /** Renders a show/hide eye and starts the field masked. */
  secureToggle?: boolean;
  /** Slotted in before the reveal control - a validity tick, a unit, a count. */
  adornment?: ReactNode;
} & Pick<
    TextInputProps,
    | 'autoCapitalize'
    | 'autoComplete'
    | 'autoFocus'
    | 'blurOnSubmit'
    | 'keyboardType'
    | 'onSubmitEditing'
    | 'placeholder'
    | 'returnKeyType'
    | 'textContentType'
  >;

/**
 * A single-line text field in the auth visual language, matching
 * `PhoneNumberField` exactly - same height, radius, border, fill, and focus
 * ring - so a form mixing the two reads as one set of controls rather than
 * two components that happen to sit together.
 */
export const AuthTextField = forwardRef<TextInput, AuthTextFieldProps>(
  function AuthTextField(
    {
      label,
      error,
      helperText,
      value,
      onChangeText,
      secureToggle = false,
      adornment,
      ...inputProps
    },
    ref,
  ) {
    const theme = useTheme();
    const styles = useThemedStyles(createStyles);
    const [focused, setFocused] = useState(false);
    const [revealed, setRevealed] = useState(false);

    /**
     * Opacity on an overlay rather than an animated `borderColor`: colour
     * cannot be driven on the native thread, so animating it would put a
     * JS-thread write on every frame of a transition that fires while the
     * keyboard is also animating in.
     */
    const focusProgress = useRef(new Animated.Value(0)).current;

    useEffect(() => {
      Animated.timing(focusProgress, {
        toValue: focused ? 1 : 0,
        duration: 160,
        useNativeDriver: true,
      }).start();
    }, [focused, focusProgress]);

    const handleFocus = useCallback(() => setFocused(true), []);
    const handleBlur = useCallback(() => setFocused(false), []);

    return (
      <AuthField error={error} helperText={helperText} label={label}>
        <View style={[styles.shell, error ? styles.shellError : null]}>
          <TextInput
            onBlur={handleBlur}
            onChangeText={onChangeText}
            onFocus={handleFocus}
            placeholderTextColor={theme.colors.hint}
            ref={ref}
            secureTextEntry={secureToggle && !revealed}
            style={styles.input}
            value={value}
            {...inputProps}
          />
          {adornment}
          {secureToggle ? (
            <Pressable
              accessibilityLabel={revealed ? 'Hide password' : 'Show password'}
              accessibilityRole="button"
              hitSlop={8}
              onPress={() => setRevealed(current => !current)}
              style={styles.revealButton}
            >
              <Icon
                color={theme.colors.hint}
                name={revealed ? 'eye-off-outline' : 'eye-outline'}
                size={20}
              />
            </Pressable>
          ) : null}
          {error ? null : (
            <Animated.View
              // Decorative, and it sits on top of the input: without this it
              // would swallow the tap that focuses the field it decorates.
              pointerEvents="none"
              style={[styles.focusRing, { opacity: focusProgress }]}
            />
          )}
        </View>
      </AuthField>
    );
  },
);

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    field: {
      gap: 8,
    },
    label: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '700',
    },
    shell: {
      flexDirection: 'row',
      alignItems: 'center',
      minHeight: 50,
      borderRadius: 10,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.background,
      paddingHorizontal: 12,
    },
    shellError: {
      borderColor: 'rgba(203,32,45,0.35)',
    },
    input: {
      flex: 1,
      minWidth: 0,
      color: theme.colors.text,
      fontSize: 15,
      // The shell owns the height; zeroing this stops Android adding its own
      // default padding on top and making this field taller than the phone
      // field beside it.
      paddingVertical: 0,
    },
    revealButton: {
      paddingLeft: 10,
      alignItems: 'center',
      justifyContent: 'center',
    },
    focusRing: {
      // Offset by the shell's own 1dp border so the ring lands exactly on top
      // of it rather than a pixel inside, which would read as a double line.
      position: 'absolute',
      top: -1,
      left: -1,
      right: -1,
      bottom: -1,
      borderRadius: 11,
      borderWidth: 1.5,
      borderColor: theme.colors.primary,
    },
    helperText: {
      color: theme.colors.hint,
      fontSize: 12,
      lineHeight: 17,
    },
    errorText: {
      color: theme.colors.deepRed,
      fontSize: 12,
      fontWeight: '700',
      lineHeight: 17,
    },
  });
