import React, { useEffect, useMemo, useRef, useState } from 'react';
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
import { api } from '@services/api';
import { firebaseAuthService } from '@services/firebaseAuth';
import {
  clearPendingRegistrationDraft,
  getPendingRegistrationDraft,
} from '@services/registrationDraft';
import { useAppActions } from '@hooks/useAppStore';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/navigationTypes';
import { navigateAfterAuth } from '@utils/authRedirect';

type Props = NativeStackScreenProps<RootStackParamList, 'OtpVerification'>;

export function OtpVerificationScreen({
  navigation,
  route,
}: Props): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const { setSession, pushToast } = useAppActions();
  const otpInputRef = useRef<TextInput | null>(null);
  const [code, setCode] = useState('');
  const [countdown, setCountdown] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [resending, setResending] = useState(false);
  const [inputFocused, setInputFocused] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const phoneDisplay = useMemo(() => {
    return `${route.params.countryDialCode} ${route.params.localPhoneNumber}`;
  }, [route.params.countryDialCode, route.params.localPhoneNumber]);
  const otpDigits = useMemo(
    () => Array.from({ length: 6 }, (_, index) => code[index] ?? ''),
    [code],
  );
  const canVerify = code.length === 6 && !submitting;

  const focusOtpInput = () => {
    otpInputRef.current?.focus();
  };

  const goBackToRegister = () => {
    clearPendingRegistrationDraft();
    firebaseAuthService.clearPendingPhoneVerification();
    navigation.goBack();
  };

  useEffect(() => {
    const timeout = setTimeout(() => {
      focusOtpInput();
    }, 250);

    return () => clearTimeout(timeout);
  }, []);

  useEffect(() => {
    if (countdown <= 0) {
      return;
    }
    const timeout = setTimeout(
      () => setCountdown(current => current - 1),
      1000,
    );
    return () => clearTimeout(timeout);
  }, [countdown]);

  const verifyOtp = async () => {
    const sanitizedCode = code.replace(/\D/g, '');
    if (sanitizedCode.length !== 6) {
      setErrorMessage('Enter the 6-digit OTP sent to your phone.');
      return;
    }

    const draft = getPendingRegistrationDraft();
    if (!draft) {
      setErrorMessage('Your registration session expired. Please start again.');
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);

    try {
      await firebaseAuthService.confirmPhoneCode(sanitizedCode);
      const response = await api.register({
        full_name: draft.fullName,
        email: draft.email,
        phone_number: draft.fullPhoneNumber,
        password: draft.password,
      });
      clearPendingRegistrationDraft();
      await firebaseAuthService.signOutFirebasePhoneAuth();
      await setSession(response.access_token, response.user, {
        appClientId: response.app_client_id ?? null,
        appKey: response.app_key ?? null,
      });
      pushToast(
        'Account created',
        'Your phone number has been verified successfully.',
        'success',
      );
      navigateAfterAuth(navigation, route.params.redirectTo);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unable to verify OTP.';
      console.error('[OtpVerificationScreen] OTP verify failed', error);
      setErrorMessage(message);
    } finally {
      setSubmitting(false);
    }
  };

  const resendOtp = async () => {
    setResending(true);
    setErrorMessage(null);
    try {
      await firebaseAuthService.startPhoneNumberSignIn(
        route.params.fullPhoneNumber,
      );
      setCode('');
      setCountdown(30);
      focusOtpInput();
      pushToast(
        'OTP sent',
        `We sent a fresh code to ${phoneDisplay}.`,
        'success',
      );
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Unable to resend OTP.';
      console.error('[OtpVerificationScreen] OTP resend failed', error);
      setErrorMessage(message);
    } finally {
      setResending(false);
    }
  };

  return (
    <AuthScreenLayout
      eyebrow="Verify Number"
      footerActionLabel="Go back"
      footerPrompt="Need to change your details?"
      onFooterAction={goBackToRegister}
      subtitle={`Enter the OTP sent to ${phoneDisplay}. We only use Firebase here to verify your phone number before creating your account.`}
      title="Verify your phone number"
      errorMessage={errorMessage}
    >
      <View style={styles.summaryCard}>
        <Text style={styles.summaryLabel}>OTP sent to</Text>
        <Text style={styles.summaryValue}>{phoneDisplay}</Text>
        <Text style={styles.summaryHint}>
          Enter the 6-digit verification code to finish creating your account.
        </Text>
      </View>

      <View style={styles.otpSection}>
        <Text style={styles.label}>6-digit OTP</Text>
        <Pressable onPress={focusOtpInput} style={styles.otpFieldShell}>
          <View style={styles.otpRow}>
            {otpDigits.map((digit, index) => {
              const isActive =
                inputFocused &&
                (code.length === 6 ? index === 5 : index === code.length);
              const isFilled = digit.length > 0;

              return (
                <View
                  key={`otp-digit-${index}`}
                  style={[
                    styles.otpBox,
                    isFilled ? styles.otpBoxFilled : null,
                    isActive ? styles.otpBoxFocused : null,
                  ]}
                >
                  <Text style={styles.otpDigit}>{digit}</Text>
                </View>
              );
            })}
          </View>
          <TextInput
            ref={otpInputRef}
            keyboardType="number-pad"
            maxLength={6}
            onBlur={() => setInputFocused(false)}
            onChangeText={value => {
              setCode(value.replace(/\D/g, '').slice(0, 6));
              setErrorMessage(null);
            }}
            onFocus={() => setInputFocused(true)}
            style={styles.hiddenInput}
            textContentType="oneTimeCode"
            value={code}
          />
        </Pressable>
        <Text style={styles.helperText}>
          We will verify the code automatically as soon as all 6 digits are
          entered.
        </Text>
      </View>

      <Pressable
        disabled={!canVerify}
        onPress={verifyOtp}
        style={[styles.button, !canVerify ? styles.buttonDisabled : null]}
      >
        <View style={styles.buttonContent}>
          {submitting ? (
            <ActivityIndicator color={theme.colors.white} size="small" />
          ) : null}
          <Text style={styles.buttonText}>
            {submitting ? 'Verifying OTP...' : 'Verify OTP'}
          </Text>
        </View>
      </Pressable>

      <View style={styles.resendRow}>
        <Text style={styles.resendText}>
          {countdown > 0
            ? `Resend OTP in ${countdown}s`
            : "Didn't receive the code?"}
        </Text>
        <Pressable
          disabled={countdown > 0 || resending}
          onPress={resendOtp}
          style={styles.resendButton}
        >
          <Text
            style={[
              styles.resendButtonText,
              countdown > 0 || resending ? styles.resendButtonDisabled : null,
            ]}
          >
            {resending ? 'Sending...' : 'Resend OTP'}
          </Text>
        </Pressable>
      </View>
    </AuthScreenLayout>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    summaryCard: {
      borderRadius: 14,
      paddingHorizontal: 14,
      paddingVertical: 12,
      backgroundColor: theme.colors.primarySoft,
      borderWidth: 1,
      borderColor: theme.colors.border,
      gap: 6,
    },
    summaryLabel: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      fontWeight: '700',
      textTransform: 'uppercase',
      letterSpacing: 0.8,
    },
    summaryValue: {
      color: theme.colors.text,
      fontSize: 16,
      fontWeight: '800',
    },
    summaryHint: {
      color: theme.colors.secondaryText,
      fontSize: 12,
      lineHeight: 18,
    },
    otpSection: {
      gap: 8,
    },
    label: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: '700',
    },
    otpFieldShell: {
      position: 'relative',
    },
    otpRow: {
      flexDirection: 'row',
      justifyContent: 'space-between',
      gap: 8,
    },
    otpBox: {
      flex: 1,
      minHeight: 56,
      borderRadius: 14,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.background,
      alignItems: 'center',
      justifyContent: 'center',
    },
    otpBoxFilled: {
      backgroundColor: theme.colors.surfaceRaised,
    },
    otpBoxFocused: {
      borderColor: theme.colors.primary,
      shadowColor: theme.colors.primary,
      shadowOpacity: theme.mode === 'dark' ? 0.24 : 0.12,
      shadowOffset: { width: 0, height: 6 },
      shadowRadius: 12,
      elevation: 2,
    },
    otpDigit: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '700',
    },
    hiddenInput: {
      position: 'absolute',
      opacity: 0,
      width: 1,
      height: 1,
      padding: 0,
      margin: 0,
    },
    helperText: {
      color: theme.colors.hint,
      fontSize: 12,
      lineHeight: 17,
      textAlign: 'center',
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
    resendRow: {
      alignItems: 'center',
      gap: 8,
      marginTop: 2,
    },
    resendText: {
      color: theme.colors.secondaryText,
      fontSize: 13,
    },
    resendButton: {
      paddingVertical: 2,
    },
    resendButtonText: {
      color: theme.colors.primary,
      fontSize: 13,
      fontWeight: '800',
    },
    resendButtonDisabled: {
      color: theme.colors.hint,
    },
  });

const styles = createStyles(theme);
