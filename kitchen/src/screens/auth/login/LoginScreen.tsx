import React, { useRef, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native';
import { ScreenContainer } from '@components/ScreenContainer';
import { AuthField } from '@components/AuthField';
import { PrimaryButton } from '@components/PrimaryButton';
import { useAppActions, useSessionState } from '@hooks/useAppStore';
import { Icon } from '@components/Icon';
import { login } from '@services/auth';
import { BOARD_COLUMNS } from '@/data/boardColumns';
import { inkOn } from '@/themePalette';
import { useTheme, useThemedStyles } from '@/theme';
import {
  hasErrors,
  loginErrorMessage,
  toKitchenSession,
  validateLoginForm,
  type LoginFormErrors,
} from '@utils/auth';
import { WIDE_LAYOUT_MIN_WIDTH, createStyles } from './styles';

const LoginScreen = () => {
  const styles = useThemedStyles(createStyles);
  const theme = useTheme();
  const { signIn } = useAppActions();
  // Set when the server ended the session (expired token, account switched
  // off, revoked). Without it a cook would find the board replaced by a
  // login screen with no idea why.
  const { expired } = useSessionState();
  const { width } = useWindowDimensions();
  const wide = width >= WIDE_LAYOUT_MIN_WIDTH;

  const passwordRef = useRef<TextInput>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fieldErrors, setFieldErrors] = useState<LoginFormErrors>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (submitting) {
      return;
    }
    const errors = validateLoginForm(email, password);
    setFieldErrors(errors);
    setFormError(null);
    if (hasErrors(errors)) {
      return;
    }
    setSubmitting(true);
    try {
      const response = await login(email.trim(), password);
      // Signing in swaps the stack to the board, which unmounts this screen,
      // so nothing below touches state on the success path.
      signIn(toKitchenSession(response));
    } catch (error) {
      setFormError(loginErrorMessage(error));
      setSubmitting(false);
    }
  };

  return (
    <ScreenContainer>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled">
          <View style={[styles.page, wide && styles.pageWide]}>
            {wide ? (
              <View style={[styles.brand, styles.brandWide]}>
                <View style={styles.mark}>
                  <Text style={styles.markText}>K</Text>
                </View>
                <Text
                  accessibilityRole="header"
                  style={[styles.brandTitle, styles.brandTitleWide]}>
                  Kitchen board
                </Text>
                <Text style={styles.brandLead}>
                  Every new order lands here the moment it is placed. Move each
                  ticket along as the food comes together.
                </Text>
                <View style={styles.chips} accessible={false}>
                  {BOARD_COLUMNS.map(column => {
                    const background = theme.status[column.status];
                    return (
                      <View
                        key={column.status}
                        style={[styles.chip, { backgroundColor: background }]}>
                        <Text style={[styles.chipText, { color: inkOn(background) }]}>
                          {column.title}
                        </Text>
                      </View>
                    );
                  })}
                </View>
              </View>
            ) : (
              <View style={styles.brandCompact}>
                <View style={[styles.mark, styles.markCompact]}>
                  <Text style={[styles.markText, styles.markTextCompact]}>K</Text>
                </View>
                <Text
                  accessibilityRole="header"
                  style={[styles.brandTitle, styles.brandTitleCompact]}>
                  Kitchen board
                </Text>
              </View>
            )}

            <View style={[styles.formColumn, wide && styles.formColumnWide]}>
              <View style={styles.card}>
                <View>
                  <Text style={styles.heading}>Sign in</Text>
                  <Text style={styles.subheading}>
                    Use the kitchen account your restaurant set up for this
                    tablet.
                  </Text>
                </View>

                {expired && !formError ? (
                  <View
                    testID="login-expired"
                    style={styles.notice}
                    accessibilityRole="alert"
                    accessibilityLiveRegion="polite">
                    <Icon name="information-circle-outline" size={20} color={theme.colors.warning} />
                    <Text style={styles.noticeText}>
                      Your session ended, so the board was closed. Sign in again to carry on.
                    </Text>
                  </View>
                ) : null}

                {formError ? (
                  <View
                    testID="login-error"
                    style={styles.banner}
                    accessibilityRole="alert"
                    accessibilityLiveRegion="polite">
                    <Text style={styles.bannerText}>{formError}</Text>
                  </View>
                ) : null}

                <AuthField
                  testID="login-email"
                  label="Email"
                  value={email}
                  onChangeText={value => {
                    setEmail(value);
                    if (fieldErrors.email) {
                      setFieldErrors(current => ({ ...current, email: undefined }));
                    }
                  }}
                  error={fieldErrors.email}
                  placeholder="kitchen@restaurant.com"
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                  autoComplete="email"
                  textContentType="username"
                  returnKeyType="next"
                  editable={!submitting}
                  onSubmitEditing={() => passwordRef.current?.focus()}
                  submitBehavior="submit"
                />

                <AuthField
                  ref={passwordRef}
                  testID="login-password"
                  label="Password"
                  secret
                  value={password}
                  onChangeText={value => {
                    setPassword(value);
                    if (fieldErrors.password) {
                      setFieldErrors(current => ({ ...current, password: undefined }));
                    }
                  }}
                  error={fieldErrors.password}
                  placeholder="At least 8 characters"
                  autoCapitalize="none"
                  autoCorrect={false}
                  autoComplete="current-password"
                  textContentType="password"
                  returnKeyType="go"
                  editable={!submitting}
                  onSubmitEditing={submit}
                />

                <PrimaryButton
                  testID="login-submit"
                  label="Sign in"
                  onPress={submit}
                  loading={submitting}
                />

                <Text style={styles.footnote}>
                  No account? The restaurant owner adds one in the admin panel,
                  under Manage → Kitchen Staff.
                </Text>
              </View>
            </View>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </ScreenContainer>
  );
};

export default LoginScreen;
