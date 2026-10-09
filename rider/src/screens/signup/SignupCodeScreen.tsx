import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useRoute, type RouteProp } from '@react-navigation/native';

import { CODE_LENGTH, CodeInput } from '@components/onboarding/CodeInput';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Icon } from '@components/ui/Icon';
import { useI18n } from '@/i18n';
import { useNav, type RootStackParamList } from '@navigation/types';
import { ApiError } from '@/services/http';
import { requestSignupCode } from '@/services/rider';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { prettyPhone } from '@utils/format';
import { haptic } from '@utils/haptics';
import { ErrorCard, SignupFrame } from './SignupFrame';

/**
 * The 6-digit code. It is checked by the server only with the password, on
 * the next screen (one request makes the account), so a wrong code comes
 * back HERE as `error`, the boxes cleared and shaken.
 *
 * While sign-up runs on a static code the server says so (`debug_code`) and
 * it is shown under the boxes - a tester should not have to know it.
 */
export function SignupCodeScreen() {
  const nav = useNav();
  const { params } = useRoute<RouteProp<RootStackParamList, 'SignupCode'>>();
  const { colors } = useTheme();
  const { t } = useI18n();
  const [code, setCode] = useState('');
  const [debugCode, setDebugCode] = useState(params.debugCode);
  const [wait, setWait] = useState(params.retryAfter);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(params.error ?? null);
  const [shake, setShake] = useState(0);

  // Back from the account screen with "wrong code": start over on the boxes.
  useEffect(() => {
    if (!params.error) return;
    setError(params.error);
    setCode('');
    setShake(n => n + 1);
  }, [params.error, params.errorAt]);

  useEffect(() => {
    if (wait <= 0) return;
    const id = setTimeout(() => setWait(w => w - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  const next = (value = code) => {
    if (value.length !== CODE_LENGTH) {
      setError(t('onboarding.code.incomplete'));
      setShake(n => n + 1);
      haptic('warning');
      return;
    }
    nav.navigate('SignupAccount', { phone: params.phone, code: value });
  };

  const resend = async () => {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      const result = await requestSignupCode(params.phone);
      setDebugCode(result.debug_code ?? null);
      setWait(result.retry_after);
      setCode('');
      setNote(t('onboarding.code.sent'));
      haptic('success');
    } catch (e) {
      haptic('error');
      setError(
        e instanceof ApiError ? e.message : t('onboarding.account.failed'),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <SignupFrame
      icon="chatbubble-ellipses-outline"
      title={t('onboarding.code.title')}
      // Nothing is sent while sign-up runs on the static test code, so it
      // must not say a code was sent.
      lead={t(debugCode ? 'onboarding.code.leadTest' : 'onboarding.code.lead', {
        phone: prettyPhone(params.phone),
      })}
      onBack={() => nav.goBack()}
    >
      <CodeInput
        value={code}
        autoFocus
        shakeKey={shake}
        error={Boolean(error)}
        onChange={value => {
          setError(null);
          setCode(value);
          // The last digit is the "Next": nothing else to decide on this screen.
          if (value.length === CODE_LENGTH) next(value);
        }}
      />
      {debugCode ? (
        <View style={[styles.test, { backgroundColor: colors.warningSoft }]}>
          <Icon name="flask-outline" size={16} color={colors.warning} />
          <AppText variant="label" tone="warning" selectable>
            {t('onboarding.code.testCode', { code: debugCode })}
          </AppText>
        </View>
      ) : null}
      {error ? <ErrorCard message={error} /> : null}
      {note && !error ? (
        <AppText variant="label" tone="success" align="center">
          {note}
        </AppText>
      ) : null}

      <Button
        label={t('onboarding.code.next')}
        icon="arrow-forward"
        onPress={() => next()}
      />

      <View style={styles.links}>
        {wait > 0 ? (
          <AppText
            variant="label"
            tone="muted"
            align="center"
            style={styles.wait}
          >
            {t('onboarding.code.resendIn', { s: wait })}
          </AppText>
        ) : (
          <Button
            kind="ghost"
            size="md"
            icon="refresh"
            label={t('onboarding.code.resend')}
            loading={busy}
            onPress={resend}
          />
        )}
        <Button
          kind="ghost"
          size="md"
          icon="create-outline"
          label={t('onboarding.code.change')}
          onPress={() => nav.popTo('SignupPhone', { phone: params.phone })}
        />
      </View>
    </SignupFrame>
  );
}

const styles = StyleSheet.create({
  test: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'center',
    gap: space.xs,
    paddingHorizontal: space.md,
    paddingVertical: space.xs + 2,
    borderRadius: radius.pill,
  },
  links: { alignItems: 'center', gap: space.xs },
  wait: { paddingVertical: space.md },
});
