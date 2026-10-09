import React, { useRef, useState } from 'react';
import { type TextInputInstance } from 'react-native';
import { useRoute, type RouteProp } from '@react-navigation/native';

import { Button } from '@components/ui/Button';
import { TextField } from '@components/ui/TextField';
import { useI18n } from '@/i18n';
import { useNav, type RootStackParamList } from '@navigation/types';
import { ApiError } from '@/services/http';
import { rememberOnboarding } from '@/services/onboardingMemory';
import { signup } from '@/services/rider';
import { useSession } from '@/store/SessionProvider';
import { haptic } from '@utils/haptics';
import { ErrorCard, SignupFrame } from './SignupFrame';

const CODE_ERRORS = new Set(['code_wrong', 'code_expired', 'code_locked']);

/**
 * Name and password, then the account is made and the rider is signed in -
 * straight onto their application, which is what they are here to fill in.
 */
export function SignupAccountScreen() {
  const nav = useNav();
  const { params } = useRoute<RouteProp<RootStackParamList, 'SignupAccount'>>();
  const { signInWithToken } = useSession();
  const { t } = useI18n();
  const [name, setName] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{
    name?: string;
    password?: string;
    confirm?: string;
  }>({});
  const [error, setError] = useState<string | null>(null);
  const [taken, setTaken] = useState(false);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<TextInputInstance>(null);
  const confirmRef = useRef<TextInputInstance>(null);

  const create = async () => {
    const problems: typeof errors = {};
    const fullName = name.split(/\s+/).filter(Boolean).join(' ');
    if (fullName.length < 2)
      problems.name = t('onboarding.account.nameProblem');
    if (password.length < 8)
      problems.password = t('onboarding.account.passwordShort');
    else if (password !== confirm)
      problems.confirm = t('onboarding.account.passwordMismatch');
    setErrors(problems);
    if (Object.keys(problems).length) {
      haptic('warning');
      return;
    }
    setBusy(true);
    setError(null);
    setTaken(false);
    try {
      const result = await signup({
        phone_number: params.phone,
        code: params.code,
        password,
        full_name: fullName,
      });
      // Before signing in, so the app opens on the application and not on
      // tabs that would vanish a second later when /rider/me answers.
      await rememberOnboarding('PENDING');
      await signInWithToken(result);
      haptic('success');
    } catch (e) {
      haptic('error');
      if (e instanceof ApiError && e.code && CODE_ERRORS.has(e.code)) {
        nav.popTo('SignupCode', {
          phone: params.phone,
          debugCode: null,
          retryAfter: 0,
          error: e.message,
          errorAt: Date.now(),
        });
        return;
      }
      if (e instanceof ApiError && e.code === 'phone_in_use') setTaken(true);
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
      icon="person-add-outline"
      title={t('onboarding.account.title')}
      lead={t('onboarding.account.lead')}
      onBack={() => nav.goBack()}
    >
      <TextField
        label={t('onboarding.account.name')}
        icon="person-outline"
        value={name}
        onChangeText={v => {
          setErrors(p => ({ ...p, name: undefined }));
          setName(v);
        }}
        error={errors.name}
        autoCapitalize="words"
        autoComplete="name"
        textContentType="name"
        returnKeyType="next"
        placeholder={t('onboarding.account.namePlaceholder')}
        onSubmitEditing={() => passwordRef.current?.focus()}
        autoFocus
      />
      <TextField
        ref={passwordRef}
        label={t('onboarding.account.password')}
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
        onSubmitEditing={create}
      />
      {taken ? (
        <ErrorCard message={t('onboarding.err.phoneInUse')}>
          <Button
            kind="secondary"
            size="md"
            icon="log-in-outline"
            label={t('onboarding.signup.signIn')}
            onPress={() => nav.popTo('Login')}
          />
        </ErrorCard>
      ) : null}
      {error ? <ErrorCard message={error} /> : null}
      <Button
        label={t('onboarding.account.create')}
        icon="checkmark"
        loading={busy}
        onPress={create}
      />
    </SignupFrame>
  );
}
