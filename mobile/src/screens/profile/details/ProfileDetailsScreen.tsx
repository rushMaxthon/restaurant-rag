import React, { useEffect, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Ionicons';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { ApiError, api } from '@services/api';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

export function ProfileDetailsScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation();
  const { user, token } = useSession();
  const { updateUser, pushToast } = useAppActions();
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (!user) {
      return;
    }
    setFullName(user.full_name);
    setEmail(user.email);
    setPhoneNumber(user.phone_number ?? '');
  }, [user]);

  if (!user) {
    return <SafeAreaView edges={['bottom']} style={styles.safeArea} />;
  }

  const save = () => {
    const trimmedName = fullName.trim();
    if (trimmedName.length < 2) {
      pushToast(
        'Name required',
        'Please enter at least 2 characters for your name.',
        'error',
      );
      return;
    }
    if (!token) {
      pushToast(
        'Session expired',
        'Please login again to update your profile.',
        'error',
      );
      return;
    }

    setIsSaving(true);
    void api
      .updateProfile(token, {
        full_name: trimmedName,
        phone_number: phoneNumber.trim() || null,
        default_address: user.default_address ?? null,
      })
      .then(updatedUser => {
        updateUser(updatedUser);
        pushToast(
          'Profile updated',
          'Your account details are now synced everywhere.',
          'success',
        );
        navigation.goBack();
      })
      .catch((error: unknown) => {
        const message =
          error instanceof ApiError
            ? error.message
            : 'Unable to save your profile right now.';
        pushToast('Save failed', message, 'error');
      })
      .finally(() => {
        setIsSaving(false);
      });
  };

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.flex}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.card}>
            <Text style={styles.heading}>Personal details</Text>
            <Text style={styles.helper}>
              Update the information used across checkout, recommendations, and
              your saved profile.
            </Text>

            <TextInput
              onChangeText={setFullName}
              placeholder="Full name"
              placeholderTextColor={theme.colors.hint}
              style={styles.input}
              value={fullName}
            />
            <TextInput
              autoCapitalize="none"
              editable={false}
              placeholder="Email"
              placeholderTextColor={theme.colors.hint}
              style={[styles.input, styles.inputDisabled]}
              value={email}
            />
            <TextInput
              keyboardType="phone-pad"
              onChangeText={setPhoneNumber}
              placeholder="Phone number"
              placeholderTextColor={theme.colors.hint}
              style={styles.input}
              value={phoneNumber}
            />
            <Pressable
              onPress={() => navigation.navigate('SavedAddresses' as never)}
              style={styles.addressCard}
            >
              <View style={styles.addressCardIcon}>
                <Icon
                  color={theme.colors.primary}
                  name="location-outline"
                  size={18}
                />
              </View>
              <View style={styles.addressCardCopy}>
                <Text style={styles.addressCardTitle}>Saved addresses</Text>
                <Text numberOfLines={2} style={styles.addressCardText}>
                  {user.default_address ??
                    'Add a default delivery address for faster checkout.'}
                </Text>
              </View>
              <Icon
                color={theme.colors.hint}
                name="chevron-forward"
                size={18}
              />
            </Pressable>
          </View>
        </ScrollView>
        <View style={styles.footer}>
          <Pressable
            disabled={isSaving}
            onPress={save}
            style={[styles.saveButton, isSaving && styles.saveButtonDisabled]}
          >
            <Text style={styles.saveButtonText}>
              {isSaving ? 'Saving...' : 'Save changes'}
            </Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      flex: 1,
      backgroundColor: theme.colors.background,
    },
    flex: {
      flex: 1,
    },
    content: {
      padding: theme.spacing.screen,
      paddingTop: theme.spacing.stackTop,
      paddingBottom: 120,
    },
    card: {
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 18,
      gap: 12,
    },
    heading: {
      color: theme.colors.text,
      fontSize: 22,
      fontWeight: '800',
    },
    helper: {
      color: theme.colors.secondaryText,
      lineHeight: 20,
      marginBottom: 4,
    },
    input: {
      minHeight: 52,
      borderRadius: 16,
      backgroundColor: theme.colors.surface,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 14,
      color: theme.colors.text,
    },
    inputDisabled: {
      color: theme.colors.secondaryText,
    },
    addressCard: {
      borderRadius: 18,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surface,
      padding: 14,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
    },
    addressCardIcon: {
      width: 40,
      height: 40,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.primarySoft,
    },
    addressCardCopy: {
      flex: 1,
      gap: 4,
    },
    addressCardTitle: {
      color: theme.colors.text,
      fontWeight: '800',
    },
    addressCardText: {
      color: theme.colors.secondaryText,
      lineHeight: 18,
    },
    footer: {
      paddingHorizontal: theme.spacing.screen,
      paddingBottom: 12,
    },
    saveButton: {
      minHeight: 52,
      borderRadius: 18,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
    },
    saveButtonDisabled: {
      opacity: 0.7,
    },
    saveButtonText: {
      color: theme.colors.white,
      fontWeight: '800',
      fontSize: 15,
    },
  });
