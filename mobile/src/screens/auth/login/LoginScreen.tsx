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
import { api } from '@services/api';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/navigationTypes';
import { navigateAfterAuth } from '@utils/authRedirect';
import {
  buildInternationalPhoneNumber,
  getCountryByCode,
  isValidPhoneNumberForCountry,
  sanitizeLocalPhoneNumber,
} from '@/utils/phoneNumber';

type Props = NativeStackScreenProps<RootStackParamList, 'Login'>;

type LoginErrors = {
  phoneNumber?: string;
  password?: string;
};

function validatePhoneNumber(value: string): boolean {
  return /^\d{8,15}$/.test(value.trim());
}

/** Total run of the entrance sequence. Long enough to read as deliberate, short
 *  enough that a returning user reaching for the field never waits on it. */
const ENTRANCE_DURATION_MS = 520;

/** How far each band travels on its way in. Small on purpose: a big slide reads
 *  as a page transition, and this is one screen settling. */
const ENTRANCE_RISE = 20;

/**
 * Initials for the brand mark, from whatever this white-label build is called.
 *
 * Two letters at most - one word gives one letter rather than a cramped pair of
 * consonants, which is how "Bangkok" would otherwise render as "BA".
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

export function LoginScreen({ navigation, route }: Props): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { setSession, pushToast } = useAppActions();
  const { appConfig } = useSession();
  const [phoneNumber, setPhoneNumber] = useState(
    route.params?.prefilledPhoneNumber ?? '',
  );
  const [country, setCountry] = useState(
    getCountryByCode(route.params?.prefilledCountryCode),
  );
  const [password, setPassword] = useState('');
  const [errors, setErrors] = useState<LoginErrors>({});
  const [apiError, setApiError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const phoneRef = useRef<TextInput>(null);
  const passwordRef = useRef<TextInput>(null);

  const login = async () => {
    const nextErrors: LoginErrors = {};
    const trimmedPhoneNumber = sanitizeLocalPhoneNumber(phoneNumber);
    const fullPhoneNumber = buildInternationalPhoneNumber(
      country,
      trimmedPhoneNumber,
    );

    if (
      !validatePhoneNumber(trimmedPhoneNumber) ||
      !isValidPhoneNumberForCountry(trimmedPhoneNumber, country)
    ) {
      nextErrors.phoneNumber = 'Enter a valid mobile number.';
    }
    if (!password.trim()) {
      nextErrors.password = 'Enter your password.';
    }

    setErrors(nextErrors);
    setApiError(null);

    if (Object.keys(nextErrors).length > 0) {
      return;
    }

    setSubmitting(true);
    try {
      const response = await api.login({
        phone_number: fullPhoneNumber,
        password,
      });
      await setSession(response.access_token, response.user, {
        appClientId: response.app_client_id ?? null,
        appKey: response.app_key ?? null,
      });
      pushToast('Welcome back', 'Your personalized feed is ready.', 'success');
      navigateAfterAuth(navigation, route.params?.redirectTo);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : 'Unable to log in.');
    } finally {
      setSubmitting(false);
    }
  };

  // --- motion --------------------------------------------------------------

  const entrance = useRef(new Animated.Value(0)).current;
  const buttonScale = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    let cancelled = false;
    // Honour the OS "reduce motion" setting rather than animating regardless:
    // this screen is the first thing some users see, and a slide-and-fade is
    // exactly the kind of movement that setting exists to suppress.
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
   * Staggers the three bands off a single driver.
   *
   * Each band reads its own slice of the same 0..1 progress, so the sequence
   * costs one native animation rather than three, and the bands cannot drift
   * apart mid-flight the way three independently scheduled timings can.
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
                  // The screen is presented modally, so each platform gets the
                  // dismissal affordance its users already read as "close this
                  // sheet": a chevron-down on iOS, a back arrow on Android.
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

            <Text style={styles.title}>Welcome back</Text>
            <Text style={styles.subtitle}>
              Log in to {brandName} for saved addresses, smarter picks, and
              one-tap checkout.
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
                onSubmitEditing={() => passwordRef.current?.focus()}
                ref={phoneRef}
                returnKeyType="next"
                selectedCountry={country}
                value={phoneNumber}
              />
            </AuthField>

            <AuthTextField
              autoComplete="current-password"
              error={errors.password}
              label="Password"
              onChangeText={value => {
                setPassword(value);
                setErrors(current => ({ ...current, password: undefined }));
                setApiError(null);
              }}
              onSubmitEditing={login}
              placeholder="Password"
              ref={passwordRef}
              returnKeyType="go"
              secureToggle
              value={password}
            />

            <Animated.View style={{ transform: [{ scale: buttonScale }] }}>
              <Pressable
                accessibilityRole="button"
                accessibilityState={{ busy: submitting, disabled: submitting }}
                disabled={submitting}
                onPress={login}
                onPressIn={pressIn}
                onPressOut={pressOut}
                style={[styles.button, submitting ? styles.buttonBusy : null]}
              >
                {submitting ? (
                  <ActivityIndicator color={theme.colors.white} size="small" />
                ) : null}
                <Text style={styles.buttonText}>
                  {submitting ? 'Logging in...' : 'Log in'}
                </Text>
              </Pressable>
            </Animated.View>
          </Animated.View>

          {/* Pushes the footer to the bottom on a tall screen while letting it
              ride up with the content on a short one, which a fixed-position
              footer cannot do once the keyboard is open. */}
          <View style={styles.spacer} />

          <Animated.View style={[styles.footer, footerBand]}>
            <Text style={styles.footerPrompt}>Don't have an account?</Text>
            <Pressable
              accessibilityRole="button"
              hitSlop={8}
              onPress={() =>
                navigation.navigate('Register', {
                  redirectTo: route.params?.redirectTo,
                  prefilledPhoneNumber: phoneNumber,
                  prefilledCountryCode: country.code,
                })
              }
            >
              <Text style={styles.footerAction}>Register</Text>
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
      // `flexGrow` rather than `flex`: the content sizes to itself and only
      // stretches to fill a tall screen, so it stays scrollable once the
      // keyboard covers the lower half.
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
      // 40dp of tappable area for a 22dp glyph: the icon stays visually light
      // while the target clears the 44dp minimum once `hitSlop` is counted.
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
      width: 60,
      height: 60,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
      // A tinted shadow rather than a neutral one: a grey drop shadow under a
      // saturated mark reads as dirt, a shadow in the mark's own hue reads as
      // light.
      shadowColor: theme.colors.primary,
      shadowOpacity: 0.32,
      shadowOffset: { width: 0, height: 8 },
      shadowRadius: 16,
      elevation: 6,
    },
    brandMarkText: {
      color: theme.colors.white,
      fontSize: 22,
      fontWeight: '900',
      letterSpacing: 0.5,
    },
    title: {
      marginTop: 28,
      color: theme.colors.text,
      fontSize: 34,
      lineHeight: 40,
      fontWeight: '800',
      // Negative tracking on display sizes only. At 34pt the default spacing
      // reads loose; the body copy below keeps its normal tracking.
      letterSpacing: -1,
    },
    subtitle: {
      marginTop: 10,
      color: theme.colors.secondaryText,
      fontSize: 15,
      lineHeight: 22,
    },

    // --- form --------------------------------------------------------------
    form: {
      marginTop: 36,
      gap: 20,
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
      minHeight: 32,
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
