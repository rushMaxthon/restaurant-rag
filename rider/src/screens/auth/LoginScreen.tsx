import React, { useRef, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, StyleSheet, View, type TextInputInstance } from 'react-native';
import Animated, { FadeInDown, FadeInUp } from 'react-native-reanimated';

import { AppText } from '@components/ui/AppText';
import { BrandMark } from '@components/ui/BrandMark';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Screen } from '@components/ui/Screen';
import { TextField } from '@components/ui/TextField';
import { SUPPORT_PHONE } from '@/config/api';
import { ApiError } from '@/services/http';
import { useSession } from '@/store/SessionProvider';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';
import { haptic } from '@utils/haptics';

export function digitsOnly(value: string): string {
  return value.replace(/\D/g, '').slice(-10);
}

export function loginProblem(phone: string, password: string): string | null {
  if (digitsOnly(phone).length !== 10) return 'Enter your 10-digit mobile number';
  if (password.length < 8) return 'Your password has at least 8 characters';
  return null;
}

/**
 * Sign in with the phone number and password the manager gave you. No
 * sign-up: riders are added by the platform admin, so the help line is here
 * rather than a "create account" link that would lead nowhere.
 */
export function LoginScreen() {
  const { signIn, state } = useSession();
  const { colors } = useTheme();
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(state.status === 'signedOut' ? state.reason : null);
  const passwordRef = useRef<TextInputInstance>(null);

  const problem = loginProblem(phone, password);

  const submit = async () => {
    if (problem) {
      setError(problem);
      haptic('warning');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signIn(`+91${digitsOnly(phone)}`, password);
      haptic('success');
    } catch (e) {
      haptic('error');
      setError(
        e instanceof ApiError && e.status === 401
          ? 'That phone number and password do not match.'
          : e instanceof Error
            ? e.message
            : 'Could not sign in. Try again.',
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen scroll contentStyle={styles.content}>
        <Animated.View entering={FadeInDown.duration(500)} style={styles.hero}>
          <BrandMark size={72} />
          <AppText variant="display" style={styles.title}>
            Welcome back
          </AppText>
          <AppText tone="muted">Sign in to start taking orders.</AppText>
        </Animated.View>

        <Animated.View entering={FadeInUp.delay(120).springify().damping(18)} style={styles.form}>
          <TextField
            label="Mobile number"
            icon="call-outline"
            prefix="+91"
            value={phone}
            onChangeText={v => {
              setError(null);
              setPhone(digitsOnly(v));
            }}
            keyboardType="phone-pad"
            autoComplete="tel"
            textContentType="telephoneNumber"
            returnKeyType="next"
            maxLength={10}
            placeholder="98765 43210"
            onSubmitEditing={() => passwordRef.current?.focus()}
          />
          <TextField
            ref={passwordRef}
            label="Password"
            icon="lock-closed-outline"
            secure
            value={password}
            onChangeText={v => {
              setError(null);
              setPassword(v);
            }}
            autoCapitalize="none"
            autoComplete="password"
            returnKeyType="go"
            placeholder="Your password"
            onSubmitEditing={submit}
          />
          {error ? (
            <Animated.View entering={FadeInDown.duration(200)}>
              <Card tone="alt" style={[styles.error, { borderColor: colors.danger }]}>
                <Icon name="alert-circle" size={20} color={colors.danger} />
                <AppText variant="label" tone="danger" style={styles.flex}>
                  {error}
                </AppText>
              </Card>
            </Animated.View>
          ) : null}
          <Button label="Sign in" icon="arrow-forward" loading={busy} onPress={submit} testID="login-submit" />
        </Animated.View>

        <View style={styles.help}>
          <AppText variant="caption" tone="muted" align="center">
            New rider or forgot your password?
          </AppText>
          <Button kind="ghost" size="md" label="Call your manager" icon="headset-outline" onPress={() => Linking.openURL(`tel:${SUPPORT_PHONE}`)} />
        </View>
      </Screen>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { flexGrow: 1, justifyContent: 'center' },
  hero: { gap: space.xs, marginBottom: space.xxxl },
  title: { marginTop: space.xl },
  form: { gap: space.lg },
  error: { flexDirection: 'row', alignItems: 'center', gap: space.sm, paddingVertical: space.md },
  help: { marginTop: space.xxxl, alignItems: 'center' },
});
