import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  AccessibilityInfo,
  ActivityIndicator,
  Animated,
  Easing,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Ionicons';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { AuthField, AuthTextField } from '@components/AuthField';
import { PhoneNumberField } from '@components/PhoneNumberField';
import { firebaseAuthService } from '@services/firebaseAuth';
import { setPendingRegistrationDraft } from '@services/registrationDraft';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/navigationTypes';
import {
  buildInternationalPhoneNumber,
  getCountryByCode,
  isValidPhoneNumberForCountry,
  sanitizeLocalPhoneNumber,
} from '@/utils/phoneNumber';

type Props = NativeStackScreenProps<RootStackParamList, 'Register'>;

type RegisterErrors = {
  fullName?: string;
  phoneNumber?: string;
  email?: string;
  password?: string;
  confirmPassword?: string;
};

function validateEmail(email: string): boolean {
  return /\S+@\S+\.\S+/.test(email);
}

function validatePhoneNumber(value: string): boolean {
  return /^\d{8,15}$/.test(value.trim());
}

/** Matches the login screen's entrance so the two read as one flow. */
const ENTRANCE_DURATION_MS = 520;
const ENTRANCE_RISE = 20;

/**
 * Initials for the brand mark, from whatever this white-label build is called.
 * Kept in step with the login screen's mark, which is the thing a user just
 * came from when they tap through to register.
 */
function brandInitials(displayName: string | undefined): string {
  const words = (displayName ?? '').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return 'RR';
  }
  if (words.length === 1) {
    return words[0].charAt(0).toUpperCase();
  }
  return (words[0].charAt(0) + words[1].charAt(0)).toUpperCase();
}

export function RegisterScreen({
  navigation,
  route,
}: Props): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { pushToast } = useAppActions();
  const { appConfig } = useSession();
  const [fullName, setFullName] = useState('');
  const [phoneNumber, setPhoneNumber] = useState(
    route.params?.prefilledPhoneNumber ?? '',
  );
  const [country, setCountry] = useState(
    getCountryByCode(route.params?.prefilledCountryCode),
  );
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [errors, setErrors] = useState<RegisterErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const phoneRef = useRef<TextInput>(null);
  const emailRef = useRef<TextInput>(null);
  const passwordRef = useRef<TextInput>(null);
  const confirmRef = useRef<TextInput>(null);

  const register = async () => {
    const nextErrors: RegisterErrors = {};
    const trimmedPhoneNumber = sanitizeLocalPhoneNumber(phoneNumber);

    if (fullName.trim().length < 2) {
      nextErrors.fullName = 'Enter your full name.';
    }
    if (
      !validatePhoneNumber(trimmedPhoneNumber) ||
      !isValidPhoneNumberForCountry(trimmedPhoneNumber, country)
    ) {
      nextErrors.phoneNumber = 'Enter a valid mobile number.';
    }
    if (!email.trim()) {
      nextErrors.email = 'Enter your email address.';
    } else if (!validateEmail(email.trim())) {
      nextErrors.email = 'Enter a valid email address.';
    }
    if (password.length < 8) {
      nextErrors.password = 'Use at least 8 characters.';
    } else if (!/[A-Za-z]/.test(password) || !/\d/.test(password)) {
      nextErrors.password = 'Use letters and numbers in your password.';
    }
    if (!confirmPassword) {
      nextErrors.confirmPassword = 'Confirm your password.';
    } else if (confirmPassword !== password) {
      nextErrors.confirmPassword = 'Passwords do not match.';
    }

    setErrors(nextErrors);
    setApiError(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    try {
      const fullPhoneNumber = buildInternationalPhoneNumber(
        country,
        trimmedPhoneNumber,
      );
      await firebaseAuthService.startPhoneNumberSignIn(fullPhoneNumber);
      setPendingRegistrationDraft({
        fullName: fullName.trim(),
        email: email.trim(),
        password,
        fullPhoneNumber,
      });
      pushToast(
        'OTP sent',
        `Verify ${fullPhoneNumber} to continue.`,
        'success',
      );
      navigation.navigate('OtpVerification', {
        localPhoneNumber: trimmedPhoneNumber,
        fullPhoneNumber,
        countryCode: country.code,
        countryDialCode: country.dialCode,
        redirectTo: route.params?.redirectTo,
      });
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unable to send OTP.';
      console.error('[RegisterScreen] OTP send failed', error);
      setApiError(message);
      pushToast('OTP failed', message, 'error');
    } finally {
      setSubmitting(false);
    }
  };

  // --- motion --------------------------------------------------------------

  const entrance = useRef(new Animated.Value(0)).current;
  const buttonScale = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    let cancelled = false;
    // Honour the OS "reduce motion" setting rather than animating regardless.
    AccessibilityInfo.isReduceMotionEnabled().then(reduceMotion => {
      if (cancelled) {
        return;
      }
      if (reduceMotion) {
        entrance.setValue(1);
        return;
      }
      Animated.timing(entrance, {
        toValue: 1,
        duration: ENTRANCE_DURATION_MS,
        easing: Easing.out(Easing.cubic),
        useNativeDriver: true,
      }).start();
    });
    return () => {
      cancelled = true;
    };
  }, [entrance]);

  /**
   * Staggers the bands off a single driver: each reads its own slice of the
   * same 0..1 progress, so the sequence costs one native animation and the
   * bands cannot drift apart the way three scheduled timings can.
   */
  const bandStyle = useCallback(
    (start: number) => {
      const progress = entrance.interpolate({
        inputRange: [start, Math.min(start + 0.65, 1)],
        outputRange: [0, 1],
        extrapolate: 'clamp',
      });
      return {
        opacity: progress,
        transform: [
          {
            translateY: progress.interpolate({
              inputRange: [0, 1],
              outputRange: [ENTRANCE_RISE, 0],
            }),
          },
        ],
      };
    },
    [entrance],
  );

  const headerBand = useMemo(() => bandStyle(0), [bandStyle]);
  const formBand = useMemo(() => bandStyle(0.18), [bandStyle]);
  const footerBand = useMemo(() => bandStyle(0.35), [bandStyle]);

  const pressIn = useCallback(() => {
    Animated.spring(buttonScale, {
      toValue: 0.97,
      useNativeDriver: true,
      speed: 45,
      bounciness: 0,
    }).start();
  }, [buttonScale]);

  const pressOut = useCallback(() => {
    Animated.spring(buttonScale, {
      toValue: 1,
      useNativeDriver: true,
      speed: 45,
      bounciness: 6,
    }).start();
  }, [buttonScale]);

  // --- render --------------------------------------------------------------

  const brandName = appConfig?.display_name ?? 'Restaurant RAG';

  /**
   * The confirm field's live tick. Shown only once the two actually match and
   * the password itself is long enough to be worth confirming, so it cannot
   * appear next to two matching but invalid entries and read as approval.
   */
  const passwordsMatch =
    confirmPassword.length > 0 &&
    confirmPassword === password &&
    password.length >= 8;

  return (
    <SafeAreaView edges={['top', 'bottom']} style={styles.safeArea}>
      <KeyboardAvoidingView
        // Android must be given an explicit behaviour, not left to the
        // manifest's `adjustResize`: from targetSdk 35 the window is
        // edge-to-edge and no longer resizes for the keyboard, so without
        // this the fields below the fold are simply unreachable.
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.flex}
      >
        <ScrollView
          contentContainerStyle={styles.scrollContent}
          keyboardDismissMode="interactive"
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <Animated.View style={[styles.header, headerBand]}>
            {navigation.canGoBack() ? (
              <Pressable
                accessibilityLabel="Close"
                accessibilityRole="button"
                hitSlop={12}
                onPress={navigation.goBack}
                style={styles.dismissButton}
              >
                <Icon
                  color={theme.colors.text}
                  // Presented modally, so each platform gets the dismissal
                  // affordance its users read as "close this sheet".
                  name={Platform.OS === 'ios' ? 'chevron-down' : 'arrow-back'}
                  size={22}
                />
              </Pressable>
            ) : null}

            <View style={styles.brandMark}>
              <Text style={styles.brandMarkText}>
                {brandInitials(appConfig?.display_name)}
              </Text>
            </View>

            <Text style={styles.title}>Create account</Text>
            <Text style={styles.subtitle}>
              Join {brandName}. We'll text you a one-time code to verify your
              number.
            </Text>
          </Animated.View>

          <Animated.View style={[styles.form, formBand]}>
            {apiError ? (
              <View style={styles.alert}>
                <Icon
                  color={theme.colors.deepRed}
                  name="alert-circle-outline"
                  size={18}
                />
                <Text style={styles.alertText}>{apiError}</Text>
              </View>
            ) : null}

            <AuthTextField
              autoComplete="name"
              blurOnSubmit={false}
              error={errors.fullName}
              label="Name"
              onChangeText={value => {
                setFullName(value);
                setErrors(current => ({ ...current, fullName: undefined }));
                setApiError(null);
              }}
              onSubmitEditing={() => phoneRef.current?.focus()}
              placeholder="Your full name"
              returnKeyType="next"
              textContentType="name"
              value={fullName}
            />

            <AuthField
              error={errors.phoneNumber}
              helperText="Tap the country code to change region."
              label="Mobile number"
            >
              <PhoneNumberField
                blurOnSubmit={false}
                hasError={Boolean(errors.phoneNumber)}
                onChangeText={value => {
                  setPhoneNumber(sanitizeLocalPhoneNumber(value));
                  setErrors(current => ({
                    ...current,
                    phoneNumber: undefined,
                  }));
                  setApiError(null);
                }}
                onSelectCountry={selectedCountry => {
                  setCountry(selectedCountry);
                  setErrors(current => ({
                    ...current,
                    phoneNumber: undefined,
                  }));
                  setApiError(null);
                }}
                onSubmitEditing={() => emailRef.current?.focus()}
                ref={phoneRef}
                returnKeyType="next"
                selectedCountry={country}
                value={phoneNumber}
              />
            </AuthField>

            <AuthTextField
              autoCapitalize="none"
              autoComplete="email"
              blurOnSubmit={false}
              error={errors.email}
              keyboardType="email-address"
              label="Email"
              onChangeText={value => {
                setEmail(value);
                setErrors(current => ({ ...current, email: undefined }));
                setApiError(null);
              }}
              onSubmitEditing={() => passwordRef.current?.focus()}
              placeholder="you@example.com"
              ref={emailRef}
              returnKeyType="next"
              textContentType="emailAddress"
              value={email}
            />

            <AuthTextField
              autoComplete="new-password"
              blurOnSubmit={false}
              error={errors.password}
              // States the rule up front instead of letting the user discover
              // it by failing submit. Same rule `register()` enforces.
              helperText="At least 8 characters, with letters and numbers."
              label="Password"
              onChangeText={value => {
                setPassword(value);
                setErrors(current => ({ ...current, password: undefined }));
                setApiError(null);
              }}
              onSubmitEditing={() => confirmRef.current?.focus()}
              placeholder="Create a password"
              ref={passwordRef}
              returnKeyType="next"
              secureToggle
              value={password}
            />

            <AuthTextField
              adornment={
                passwordsMatch ? (
                  <Icon
                    color={theme.colors.success}
                    name="checkmark-circle"
                    size={20}
                  />
                ) : null
              }
              autoComplete="new-password"
              error={errors.confirmPassword}
              label="Confirm password"
              onChangeText={value => {
                setConfirmPassword(value);
                setErrors(current => ({
                  ...current,
                  confirmPassword: undefined,
                }));
                setApiError(null);
              }}
              onSubmitEditing={register}
              placeholder="Re-enter your password"
              ref={confirmRef}
              returnKeyType="go"
              secureToggle
              value={confirmPassword}
            />

            <Animated.View style={{ transform: [{ scale: buttonScale }] }}>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ busy: submitting, disabled: submitting }}
                disabled={submitting}
                onPress={register}
                onPressIn={pressIn}
                onPressOut={pressOut}
                style={[styles.button, submitting ? styles.buttonBusy : null]}
              >
                {submitting ? (
                  <ActivityIndicator color={theme.colors.white} size="small" />
                ) : null}
                <Text style={styles.buttonText}>
                  {submitting ? 'Sending OTP...' : 'Create account'}
                </Text>
              </Pressable>
            </Animated.View>
          </Animated.View>

          {/* Pushes the footer to the bottom when the form is shorter than the
              screen, and simply follows it when it is not. */}
          <View style={styles.spacer} />

          <Animated.View style={[styles.footer, footerBand]}>
            <Text style={styles.footerPrompt}>Already have an account?</Text>
            <Pressable
              accessibilityRole="button"
              hitSlop={8}
              onPress={() =>
                navigation.navigate('Login', {
                  redirectTo: route.params?.redirectTo,
                  prefilledPhoneNumber: phoneNumber,
                  prefilledCountryCode: country.code,
                })
              }
            >
              <Text style={styles.footerAction}>Log in</Text>
            </Pressable>
          </Animated.View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    flex: {
      flex: 1,
    },
    scrollContent: {
      flexGrow: 1,
      paddingHorizontal: 24,
      paddingTop: 8,
      paddingBottom: 16,
    },

    // --- header ------------------------------------------------------------
    header: {
      paddingTop: 8,
    },
    dismissButton: {
      width: 40,
      height: 40,
      marginLeft: -8,
      marginBottom: 12,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.chip,
    },
    brandMark: {
      // 52dp against the login screen's 60dp: this form is five fields long,
      // so the header buys its breathing room back from the mark rather than
      // from the space between the fields.
      width: 52,
      height: 52,
      borderRadius: 18,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
      // Tinted in the mark's own hue: a neutral grey shadow under saturated
      // orange reads as dirt, a shadow in the hue reads as light.
      shadowColor: theme.colors.primary,
      shadowOpacity: 0.32,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 6,
    },
    brandMarkText: {
      color: theme.colors.white,
      fontSize: 20,
      fontWeight: '900',
      letterSpacing: 0.5,
    },
    title: {
      marginTop: 22,
      color: theme.colors.text,
      fontSize: 30,
      lineHeight: 36,
      fontWeight: '800',
      letterSpacing: -0.9,
    },
    subtitle: {
      marginTop: 8,
      color: theme.colors.secondaryText,
      fontSize: 15,
      lineHeight: 22,
    },

    // --- form --------------------------------------------------------------
    form: {
      marginTop: 28,
      // 18 against login's 20: five fields multiply every gap, so the form
      // tightens slightly to keep the submit button closer to the fold.
      gap: 18,
    },
    alert: {
      flexDirection: 'row',
      alignItems: 'flex-start',
      gap: 10,
      borderRadius: 14,
      paddingHorizontal: 14,
      paddingVertical: 12,
      backgroundColor: theme.colors.dangerSoft,
      borderWidth: 1,
      borderColor:
        theme.mode === 'dark' ? 'rgba(203,32,45,0.26)' : 'rgba(203,32,45,0.14)',
    },
    alertText: {
      flex: 1,
      color: theme.colors.deepRed,
      fontSize: 13,
      lineHeight: 19,
      fontWeight: '700',
    },
    button: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 10,
      minHeight: 54,
      borderRadius: 14,
      backgroundColor: theme.colors.primary,
      marginTop: 4,
      shadowColor: theme.colors.primary,
      shadowOpacity: 0.28,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 4,
    },
    buttonBusy: {
      opacity: 0.72,
    },
    buttonText: {
      color: theme.colors.white,
      fontSize: 16,
      fontWeight: '800',
      letterSpacing: 0.2,
    },

    // --- footer ------------------------------------------------------------
    spacer: {
      flex: 1,
      minHeight: 28,
    },
    footer: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      flexWrap: 'wrap',
      gap: 6,
      paddingTop: 24,
    },
    footerPrompt: {
      color: theme.colors.secondaryText,
      fontSize: 14,
    },
    footerAction: {
      color: theme.colors.primary,
      fontSize: 14,
      fontWeight: '800',
    },
  });
