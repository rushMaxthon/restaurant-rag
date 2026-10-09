import React, { useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Linking,
  Platform,
  StyleSheet,
  View,
  type TextInputInstance,
} from 'react-native';
import Animated, { FadeInDown, FadeInUp } from 'react-native-reanimated';

import { LanguageButton } from '@components/LanguageSwitch';
import { AppText } from '@components/ui/AppText';
import { BrandMark } from '@components/ui/BrandMark';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Screen } from '@components/ui/Screen';
import { TextField } from '@components/ui/TextField';
import { SUPPORT_PHONE } from '@/config/api';
import { useI18n } from '@/i18n';
import { translate } from '@/i18n/translate';
import { ApiError } from '@/services/http';
import { useNav } from '@navigation/types';
import { useSession } from '@/store/SessionProvider';
import { useTheme } from '@theme/ThemeProvider';
import { space, motion } from '@theme/tokens';
import { haptic } from '@utils/haptics';

export function digitsOnly(value: string): string {
  return value.replace(/\D/g, '').slice(-10);
}

export function loginProblem(phone: string, password: string): string | null {
  if (digitsOnly(phone).length !== 10)
    return translate('account.login.phoneProblem');
  if (password.length < 8) return translate('account.login.passwordProblem');
  return null;
}

/**
 * Sign in with the phone number and password - given by the manager, or
 * chosen at sign-up. "Become a rider" sits right under Sign in, because a
 * newcomer who opens the app looks for it there first; the help line stays
 * for a forgotten password.
 */
export function LoginScreen() {
  const { signIn, state } = useSession();
  const { colors } = useTheme();
  const { t } = useI18n();
  const nav = useNav();
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(
    state.status === 'signedOut' ? state.reason : null,
  );
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
          ? t('account.login.mismatch')
          : e instanceof Error
          ? e.message
          : t('account.login.failed'),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <Screen scroll contentStyle={styles.content}>
        <Animated.View entering={FadeInDown.duration(500)} style={styles.hero}>
          <View style={styles.brandRow}>
            <BrandMark size={72} />
            <LanguageButton />
          </View>
          <AppText variant="display" style={styles.title}>
            {t('account.login.welcome')}
          </AppText>
          <AppText tone="muted">{t('account.login.lead')}</AppText>
        </Animated.View>

        <Animated.View
          entering={FadeInUp.delay(120).duration(motion.base)}
          style={styles.form}
        >
          <TextField
            label={t('account.login.mobile')}
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
            label={t('account.login.password')}
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
            placeholder={t('account.login.passwordPlaceholder')}
            onSubmitEditing={submit}
          />
          {error ? (
            <Animated.View entering={FadeInDown.duration(200)}>
              <Card
                tone="alt"
                style={[styles.error, { borderColor: colors.danger }]}
              >
                <Icon name="alert-circle" size={20} color={colors.danger} />
                <AppText variant="label" tone="danger" style={styles.flex}>
                  {error}
                </AppText>
              </Card>
            </Animated.View>
          ) : null}
          <Button
            label={t('account.login.signIn')}
            icon="arrow-forward"
            loading={busy}
            onPress={submit}
            testID="login-submit"
          />
          <Button
            kind="secondary"
            icon="bicycle-outline"
            label={t('onboarding.signup.newHere')}
            onPress={() =>
              nav.navigate('SignupPhone', { phone: digitsOnly(phone) || undefined })
            }
            testID="login-signup"
          />
        </Animated.View>

        <View style={styles.help}>
          <AppText variant="caption" tone="muted" align="center">
            {t('account.login.help')}
          </AppText>
          <Button
            kind="ghost"
            size="md"
            label={t('account.login.callManager')}
            icon="headset-outline"
            onPress={() => Linking.openURL(`tel:${SUPPORT_PHONE}`)}
          />
        </View>
      </Screen>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { flexGrow: 1, justifyContent: 'center' },
  hero: { gap: space.xs, marginBottom: space.xxxl },
  brandRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  title: { marginTop: space.xl },
  form: { gap: space.lg },
  error: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    paddingVertical: space.md,
  },
  help: { marginTop: space.xxxl, alignItems: 'center' },
});
