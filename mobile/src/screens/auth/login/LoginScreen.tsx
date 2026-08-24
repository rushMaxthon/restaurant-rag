import React, { useState } from 'react';
import {
  ActivityIndicator,
  PixelRatio,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { AuthScreenLayout } from '@components/AuthScreenLayout';
import {
  CountryCodePicker,
  PHONE_INPUT_MIN_WIDTH,
} from '@components/CountryCodePicker';
import { api } from '@services/api';
import { useAppActions } from '@hooks/useAppStore';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
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

export function LoginScreen({ navigation, route }: Props): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { setSession, pushToast } = useAppActions();
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

  return (
    <AuthScreenLayout
      eyebrow="Welcome Back"
      footerActionLabel="Register"
      footerPrompt="Don't have an account?"
      onFooterAction={() =>
        navigation.navigate('Register', {
          redirectTo: route.params?.redirectTo,
          prefilledPhoneNumber: phoneNumber,
          prefilledCountryCode: country.code,
        })
      }
      subtitle="Login with your mobile number to continue with saved addresses, smarter suggestions, and quick checkout."
      title="Fast phone login for your next craving"
      errorMessage={apiError}
    >
      <View style={styles.field}>
        <Text style={styles.label}>Mobile number</Text>
        <View style={styles.phoneRow}>
          <CountryCodePicker
            onSelect={selectedCountry => {
              setCountry(selectedCountry);
              setErrors(current => ({ ...current, phoneNumber: undefined }));
              setApiError(null);
            }}
            selectedCountry={country}
          />
          <TextInput
            autoComplete="tel"
            keyboardType="number-pad"
            maxLength={15}
            onChangeText={value => {
              setPhoneNumber(sanitizeLocalPhoneNumber(value));
              setErrors(current => ({ ...current, phoneNumber: undefined }));
              setApiError(null);
            }}
            placeholder="Enter your mobile number"
            placeholderTextColor={theme.colors.hint}
            style={[
              styles.input,
              styles.phoneInput,
              errors.phoneNumber ? styles.inputError : null,
            ]}
            value={phoneNumber}
          />
        </View>
        <Text style={styles.helperText}>
          Tap the country code to change region.
        </Text>
        {errors.phoneNumber ? (
          <Text style={styles.error}>{errors.phoneNumber}</Text>
        ) : null}
      </View>

      <View style={styles.field}>
        <Text style={styles.label}>Password</Text>
        <TextInput
          autoComplete="current-password"
          onChangeText={value => {
            setPassword(value);
            setErrors(current => ({ ...current, password: undefined }));
            setApiError(null);
          }}
          placeholder="Enter your password"
          placeholderTextColor={theme.colors.hint}
          secureTextEntry
          style={[styles.input, errors.password ? styles.inputError : null]}
          value={password}
        />
        {errors.password ? (
          <Text style={styles.error}>{errors.password}</Text>
        ) : null}
      </View>

      <Pressable
        disabled={submitting}
        onPress={login}
        style={[styles.button, submitting ? styles.buttonDisabled : null]}
      >
        <View style={styles.buttonContent}>
          {submitting ? (
            <ActivityIndicator color={theme.colors.white} size="small" />
          ) : null}
          <Text style={styles.buttonText}>
            {submitting ? 'Logging in...' : 'Login'}
          </Text>
        </View>
      </Pressable>
    </AuthScreenLayout>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    field: {
      gap: 8,
    },
    label: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '700',
    },
    input: {
      minHeight: 50,
      borderRadius: 10,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.background,
      paddingHorizontal: 14,
      color: theme.colors.text,
      fontSize: 15,
    },
    phoneRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      // Lets the number field drop onto its own full-width line when the row
      // cannot give it `phoneInput.minWidth`. Nothing moves at normal sizes on
      // a normal phone; it only engages where the field would otherwise be too
      // narrow to show its placeholder.
      flexWrap: 'wrap',
    },
    phoneInput: {
      flex: 1,
      // The wrap threshold, not a cosmetic width: the width below which
      // "Enter your mobile number" starts being cut off mid-word.
      //
      // 168dp of text at fontSize 15 plus the input's 28dp of horizontal
      // padding. Multiplied by the OS font scale because the placeholder grows
      // with it while the row does not — which is why this clipped on devices
      // that look fine at 100%.
      //
      // Sized so nothing moves in the common case: a 393dp screen at 100%
      // leaves the field 197dp, just over the 196dp it needs, so it stays
      // beside the country chip exactly as it does today. A narrower screen or
      // a larger font drops it to its own full-width line instead of clipping.
      minWidth: PHONE_INPUT_MIN_WIDTH * PixelRatio.getFontScale(),
    },
    helperText: {
      color: theme.colors.hint,
      fontSize: 12,
      lineHeight: 17,
    },
    inputError: {
      borderColor: 'rgba(203,32,45,0.35)',
    },
    error: {
      color: theme.colors.deepRed,
      fontSize: 12,
      fontWeight: '700',
      lineHeight: 18,
    },
    button: {
      minHeight: 48,
      borderRadius: 10,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primary,
      marginTop: 4,
    },
    buttonDisabled: {
      opacity: 0.72,
    },
    buttonContent: {
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 10,
    },
    buttonText: {
      color: theme.colors.white,
      fontSize: 15,
      fontWeight: '800',
    },
  });

export const styles = createStyles(theme);
