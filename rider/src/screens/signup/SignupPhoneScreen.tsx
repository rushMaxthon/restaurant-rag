import React, { useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useRoute, type RouteProp } from '@react-navigation/native';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { Icon, type IconName } from '@components/ui/Icon';
import { TextField } from '@components/ui/TextField';
import { useI18n, type Key } from '@/i18n';
import { useNav, type RootStackParamList } from '@navigation/types';
import { digitsOnly } from '@screens/auth/LoginScreen';
import { ApiError } from '@/services/http';
import { requestResetCode, requestSignupCode } from '@/services/rider';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';
import { haptic } from '@utils/haptics';
import { ErrorCard, SignupFrame } from './SignupFrame';

const NEED: { icon: IconName; key: Key }[] = [
  { icon: 'card-outline', key: 'onboarding.signup.needAadhaar' },
  { icon: 'card-outline', key: 'onboarding.signup.needPan' },
  { icon: 'business-outline', key: 'onboarding.signup.needBank' },
  { icon: 'id-card-outline', key: 'onboarding.signup.needLicence' },
];

/**
 * Step one of becoming a rider: the phone number. Asked first, and checked
 * against existing accounts before any code goes out, so somebody who is
 * already a rider is sent to sign in rather than through a sign-up that ends
 * in "this number is taken".
 *
 * `purpose: 'reset'` is forgot-password on the same screen: the number must
 * be an account this time, and one that is not is pointed at sign-up.
 */
export function SignupPhoneScreen() {
  const nav = useNav();
  const route = useRoute<RouteProp<RootStackParamList, 'SignupPhone'>>();
  const { colors } = useTheme();
  const { t } = useI18n();
  const [phone, setPhone] = useState(digitsOnly(route.params?.phone ?? ''));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [taken, setTaken] = useState(false);
  const [unknown, setUnknown] = useState(false);
  const reset = route.params?.purpose === 'reset';

  const send = async () => {
    const digits = digitsOnly(phone);
    if (digits.length !== 10) {
      setError(t('account.login.phoneProblem'));
      haptic('warning');
      return;
    }
    setBusy(true);
    setError(null);
    setTaken(false);
    setUnknown(false);
    try {
      const number = `+91${digits}`;
      const result = reset
        ? await requestResetCode(number)
        : await requestSignupCode(number);
      nav.navigate('SignupCode', {
        phone: number,
        purpose: reset ? 'reset' : 'signup',
        debugCode: result.debug_code ?? null,
        retryAfter: result.retry_after,
      });
    } catch (e) {
      haptic('error');
      if (e instanceof ApiError && e.code === 'phone_in_use') setTaken(true);
      else if (e instanceof ApiError && e.code === 'no_account') setUnknown(true);
      else
        setError(
          e instanceof Error ? e.message : t('onboarding.account.failed'),
        );
    } finally {
      setBusy(false);
    }
  };

  return (
    <SignupFrame
      icon={reset ? 'key-outline' : 'bicycle'}
      title={t(reset ? 'reset.title' : 'onboarding.signup.title')}
      lead={t(reset ? 'reset.lead' : 'onboarding.signup.lead')}
      onBack={() => nav.goBack()}
    >
      <TextField
        label={t('account.login.mobile')}
        icon="call-outline"
        prefix="+91"
        value={phone}
        onChangeText={v => {
          setError(null);
          setTaken(false);
          setUnknown(false);
          setPhone(digitsOnly(v));
        }}
        keyboardType="phone-pad"
        autoComplete="tel"
        textContentType="telephoneNumber"
        returnKeyType="go"
        maxLength={10}
        placeholder="98765 43210"
        onSubmitEditing={send}
        autoFocus
      />
      {taken ? (
        <ErrorCard message={t('onboarding.err.phoneInUse')}>
          <Button
            kind="secondary"
            size="md"
            icon="log-in-outline"
            label={t('onboarding.signup.signIn')}
            onPress={() => nav.navigate('Login')}
          />
        </ErrorCard>
      ) : null}
      {unknown ? (
        <ErrorCard message={t('reset.noAccount')}>
          <Button
            kind="secondary"
            size="md"
            icon="bicycle-outline"
            label={t('reset.signUp')}
            onPress={() =>
              nav.replace('SignupPhone', { phone: digitsOnly(phone), purpose: 'signup' })
            }
          />
        </ErrorCard>
      ) : null}
      {error ? <ErrorCard message={error} /> : null}
      <Button
        label={t('onboarding.signup.sendCode')}
        icon="arrow-forward"
        loading={busy}
        onPress={send}
      />

      {reset ? null : (
        <>
      <Card style={styles.need}>
        <AppText variant="micro" tone="muted">
          {t('onboarding.signup.needTitle').toUpperCase()}
        </AppText>
        {NEED.map(row => (
          <View key={row.key} style={styles.needRow}>
            <Icon name={row.icon} size={20} color={colors.primary} />
            <AppText variant="label" style={styles.flex}>
              {t(row.key)}
            </AppText>
          </View>
        ))}
      </Card>

      <View style={styles.footer}>
        <AppText variant="label" tone="muted">
          {t('onboarding.signup.haveAccount')}
        </AppText>
        <Button
          kind="ghost"
          size="md"
          label={t('onboarding.signup.signIn')}
          onPress={() => nav.navigate('Login')}
        />
      </View>
        </>
      )}
    </SignupFrame>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  need: { gap: space.md, marginTop: space.sm },
  needRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    flexWrap: 'wrap',
  },
});
