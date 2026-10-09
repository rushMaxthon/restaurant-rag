import React, { useRef, useState } from 'react';
import { type TextInputInstance } from 'react-native';
import { useRoute, type RouteProp } from '@react-navigation/native';

import { Button } from '@components/ui/Button';
import { TextField } from '@components/ui/TextField';
import { useI18n } from '@/i18n';
import { useNav, type RootStackParamList } from '@navigation/types';
import { ApiError } from '@/services/http';
import { resetPassword } from '@/services/rider';
import { useSession } from '@/store/SessionProvider';
import { haptic } from '@utils/haptics';
import { ErrorCard, SignupFrame } from './SignupFrame';

const CODE_ERRORS = new Set(['code_wrong', 'code_expired', 'code_locked']);

/**
 * The last step of forgot-password: a new password, twice, and the rider is
 * signed straight in - they proved the phone is theirs a moment ago. The
 * server ends every other session at the same time, which is the point when
 * the reason for the reset is a lost phone.
 */
export function ResetPasswordScreen() {
  const nav = useNav();
  const { params } = useRoute<RouteProp<RootStackParamList, 'ResetPassword'>>();
  const { signInWithToken } = useSession();
  const { t } = useI18n();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{ password?: string; confirm?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const confirmRef = useRef<TextInputInstance>(null);

  const save = async () => {
    const problems: typeof errors = {};
    if (password.length < 8) problems.password = t('onboarding.account.passwordShort');
    else if (password !== confirm) problems.confirm = t('onboarding.account.passwordMismatch');
    setErrors(problems);
    if (Object.keys(problems).length) {
      haptic('warning');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await resetPassword({
        phone_number: params.phone,
        code: params.code,
        password,
      });
      await signInWithToken(result);
      haptic('success');
    } catch (e) {
      haptic('error');
      // The code ran out or was used meanwhile: back to the boxes to get a
      // new one, the way sign-up does it.
      if (e instanceof ApiError && e.code && CODE_ERRORS.has(e.code)) {
        nav.popTo('SignupCode', {
          phone: params.phone,
          purpose: 'reset',
          debugCode: null,
          retryAfter: 0,
          error: e.message,
          errorAt: Date.now(),
        });
        return;
      }
      setError(e instanceof Error ? e.message : t('onboarding.account.failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SignupFrame
      icon="key-outline"
      title={t('reset.newTitle')}
      lead={t('reset.newLead')}
      onBack={() => nav.goBack()}
    >
      <TextField
        label={t('reset.newPassword')}
        icon="lock-closed-outline"
        secure
        value={password}
        onChangeText={v => {
          setErrors(p => ({ ...p, password: undefined }));
          setPassword(v);
        }}
        error={errors.password}
        autoCapitalize="none"
        autoComplete="new-password"
        textContentType="newPassword"
        returnKeyType="next"
        placeholder={t('onboarding.account.passwordPlaceholder')}
        onSubmitEditing={() => confirmRef.current?.focus()}
        autoFocus
      />
      <TextField
        ref={confirmRef}
        label={t('onboarding.account.confirm')}
        icon="lock-closed-outline"
        secure
        value={confirm}
        onChangeText={v => {
          setErrors(p => ({ ...p, confirm: undefined }));
          setConfirm(v);
        }}
        error={errors.confirm}
        autoCapitalize="none"
        autoComplete="new-password"
        returnKeyType="go"
        placeholder={t('onboarding.account.confirmPlaceholder')}
        onSubmitEditing={save}
      />
      {error ? <ErrorCard message={error} /> : null}
      <Button
        label={t('reset.save')}
        icon="checkmark"
        loading={busy}
        onPress={save}
        testID="reset-save"
      />
    </SignupFrame>
  );
}
