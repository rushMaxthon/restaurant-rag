import React, { useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import type { NativeStackScreenProps } from '@react-navigation/native-stack';
import { AuthScreenLayout } from '@components/AuthScreenLayout';
import { CountryCodePicker } from '@components/CountryCodePicker';
import { firebaseAuthService } from '@services/firebaseAuth';
import { setPendingRegistrationDraft } from '@services/registrationDraft';
import { useAppActions } from '@hooks/useAppStore';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
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

export function RegisterScreen({
  navigation,
  route,
}: Props): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { pushToast } = useAppActions();
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

  return (
    <AuthScreenLayout
      eyebrow="Create Account"
      footerActionLabel="Login"
      footerPrompt="Already have an account?"
      onFooterAction={() =>
        navigation.navigate('Login', {
          redirectTo: route.params?.redirectTo,
          prefilledPhoneNumber: phoneNumber,
          prefilledCountryCode: country.code,
        })
      }
      subtitle="Create your account with your name, mobile number, email, and password. We will verify your phone number with a secure OTP before creating your account."
      title="Create your account"
      errorMessage={apiError}
    >
      <View style={styles.field}>
        <Text style={styles.label}>Name</Text>
        <TextInput
          autoComplete="name"
          onChangeText={value => {
            setFullName(value);
            setErrors(current => ({ ...current, fullName: undefined }));
            setApiError(null);
          }}
          placeholder="Enter your full name"
          placeholderTextColor={theme.colors.hint}
          style={[styles.input, errors.fullName ? styles.inputError : null]}
          value={fullName}
        />
        {errors.fullName ? (
          <Text style={styles.error}>{errors.fullName}</Text>
        ) : null}
      </View>

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
        <Text style={styles.label}>Email</Text>
        <TextInput
          autoCapitalize="none"
          autoComplete="email"
          keyboardType="email-address"
          onChangeText={value => {
            setEmail(value);
            setErrors(current => ({ ...current, email: undefined }));
            setApiError(null);
          }}
          placeholder="Enter your email"
          placeholderTextColor={theme.colors.hint}
          style={[styles.input, errors.email ? styles.inputError : null]}
          value={email}
        />
        {errors.email ? <Text style={styles.error}>{errors.email}</Text> : null}
      </View>

      <View style={styles.field}>
        <Text style={styles.label}>Password</Text>
        <TextInput
          autoComplete="new-password"
          onChangeText={value => {
            setPassword(value);
            setErrors(current => ({ ...current, password: undefined }));
            setApiError(null);
          }}
          placeholder="Create a password"
          placeholderTextColor={theme.colors.hint}
          secureTextEntry
          style={[styles.input, errors.password ? styles.inputError : null]}
          value={password}
        />
        {errors.password ? (
          <Text style={styles.error}>{errors.password}</Text>
        ) : null}
      </View>

      <View style={styles.field}>
        <Text style={styles.label}>Confirm Password</Text>
        <TextInput
          autoComplete="new-password"
          onChangeText={value => {
            setConfirmPassword(value);
            setErrors(current => ({ ...current, confirmPassword: undefined }));
            setApiError(null);
          }}
          placeholder="Confirm your password"
          placeholderTextColor={theme.colors.hint}
          secureTextEntry
          style={[
            styles.input,
            errors.confirmPassword ? styles.inputError : null,
          ]}
          value={confirmPassword}
        />
        {errors.confirmPassword ? (
          <Text style={styles.error}>{errors.confirmPassword}</Text>
        ) : null}
      </View>

      <Pressable
        disabled={submitting}
        onPress={register}
        style={[styles.button, submitting ? styles.buttonDisabled : null]}
      >
        <View style={styles.buttonContent}>
          {submitting ? (
            <ActivityIndicator color={theme.colors.white} size="small" />
          ) : null}
          <Text style={styles.buttonText}>
            {submitting ? 'Sending OTP...' : 'Create Account'}
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
    },
    phoneInput: {
      flex: 1,
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
