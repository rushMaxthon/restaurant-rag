import React, { useEffect, useMemo, useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';
import type { RouteProp } from '@react-navigation/native';
import Icon from 'react-native-vector-icons/Ionicons';
import { ApiError, api } from '@services/api';
import { useAppActions, useSession } from '@hooks/useAppStore';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';
import type { RootStackParamList } from '@/navigation/navigationTypes';
import type {
  SavedAddress,
  SavedAddressLabel,
  SavedAddressPayload,
} from '@/types/app';
import { savedAddressLabelCopy } from './addressUtils';

type AddressEditorRoute = RouteProp<RootStackParamList, 'SavedAddressEditor'>;
type AddressEditorNavigation = NativeStackNavigationProp<
  RootStackParamList,
  'SavedAddressEditor'
>;

interface FormState {
  label: SavedAddressLabel;
  addressLine1: string;
  addressLine2: string;
  landmark: string;
  city: string;
  state: string;
  postalCode: string;
  phoneNumber: string;
  isDefault: boolean;
}

const emptyForm: FormState = {
  label: 'HOME',
  addressLine1: '',
  addressLine2: '',
  landmark: '',
  city: '',
  state: '',
  postalCode: '',
  phoneNumber: '',
  isDefault: false,
};

export function SavedAddressEditorScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const navigation = useNavigation<AddressEditorNavigation>();
  const route = useRoute<AddressEditorRoute>();
  const { token, user } = useSession();
  const { updateUser, pushToast } = useAppActions();
  const [addresses, setAddresses] = useState<SavedAddress[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [createSeeded, setCreateSeeded] = useState(
    route.params.mode === 'edit',
  );
  const editAddressId =
    route.params.mode === 'edit' ? route.params.addressId : null;

  const editingAddress = useMemo(
    () =>
      editAddressId
        ? addresses.find(address => address.id === editAddressId) ?? null
        : null,
    [addresses, editAddressId],
  );

  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    void api
      .getSavedAddresses(token)
      .then(rows => {
        if (!active) {
          return;
        }
        setAddresses(rows);
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError
            ? error.message
            : 'Unable to load this address.';
        pushToast('Address unavailable', message, 'error');
        navigation.goBack();
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [navigation, pushToast, token]);

  useEffect(() => {
    if (route.params.mode !== 'create' || createSeeded || loading) {
      return;
    }

    setForm(current => ({
      ...current,
      phoneNumber: current.phoneNumber || user?.phone_number || '',
      isDefault: addresses.length === 0,
    }));
    setCreateSeeded(true);
  }, [
    addresses.length,
    createSeeded,
    loading,
    route.params.mode,
    user?.phone_number,
  ]);

  useEffect(() => {
    if (!editingAddress) {
      return;
    }
    setForm({
      label: editingAddress.label,
      addressLine1: editingAddress.address_line_1,
      addressLine2: editingAddress.address_line_2 ?? '',
      landmark: editingAddress.landmark ?? '',
      city: editingAddress.city,
      state: editingAddress.state,
      postalCode: editingAddress.postal_code,
      phoneNumber: editingAddress.phone_number ?? '',
      isDefault: editingAddress.is_default,
    });
  }, [editingAddress]);

  const save = async () => {
    if (!token) {
      pushToast(
        'Session expired',
        'Please login again to manage addresses.',
        'error',
      );
      return;
    }

    const payload: SavedAddressPayload = {
      label: form.label,
      address_line_1: form.addressLine1.trim(),
      address_line_2: form.addressLine2.trim() || null,
      landmark: form.landmark.trim() || null,
      city: form.city.trim(),
      state: form.state.trim(),
      postal_code: form.postalCode.trim(),
      phone_number: form.phoneNumber.trim() || null,
      is_default: form.isDefault,
    };

    if (
      payload.address_line_1.length < 3 ||
      payload.city.length < 2 ||
      payload.state.length < 2 ||
      payload.postal_code.length < 4
    ) {
      pushToast(
        'Complete required fields',
        'Add a proper address, city, state, and postal code before saving.',
        'error',
      );
      return;
    }

    setSaving(true);
    try {
      const savedAddress =
        route.params.mode === 'edit' && editAddressId
          ? await api.updateSavedAddress(token, editAddressId, payload)
          : await api.createSavedAddress(token, payload);

      if (savedAddress.is_default && user) {
        updateUser({
          ...user,
          default_address: savedAddress.formatted_address,
        });
      }

      pushToast(
        route.params.mode === 'edit' ? 'Address updated' : 'Address added',
        'Your saved delivery address is ready to use.',
        'success',
      );
      navigation.goBack();
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : 'Unable to save this address.';
      pushToast('Save failed', message, 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        style={styles.flex}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          showsVerticalScrollIndicator={false}
        >
          <View style={styles.hero}>
            <Text style={styles.heading}>
              {route.params.mode === 'edit'
                ? 'Edit address'
                : 'Add new address'}
            </Text>
            <Text style={styles.helper}>
              Save a delivery location that checkout can use instantly.
            </Text>
          </View>

          <View style={styles.labelRow}>
            {(['HOME', 'WORK', 'OTHER'] as const).map(option => {
              const active = form.label === option;
              return (
                <Pressable
                  key={option}
                  onPress={() =>
                    setForm(current => ({ ...current, label: option }))
                  }
                  style={[
                    styles.labelChip,
                    active ? styles.labelChipActive : null,
                  ]}
                >
                  <Text
                    style={[
                      styles.labelChipText,
                      active ? styles.labelChipTextActive : null,
                    ]}
                  >
                    {savedAddressLabelCopy[option]}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          <View style={styles.card}>
            <Field
              label="House / Flat / Block"
              onChangeText={value =>
                setForm(current => ({ ...current, addressLine2: value }))
              }
              placeholder="Flat 203, Lotus Heights"
              styles={styles}
              theme={theme}
              value={form.addressLine2}
            />
            <Field
              label="Full address"
              multiline
              onChangeText={value =>
                setForm(current => ({ ...current, addressLine1: value }))
              }
              placeholder="Street name, area, road"
              styles={styles}
              theme={theme}
              value={form.addressLine1}
            />
            <Field
              label="Landmark"
              onChangeText={value =>
                setForm(current => ({ ...current, landmark: value }))
              }
              placeholder="Near metro station"
              styles={styles}
              theme={theme}
              value={form.landmark}
            />
            <View style={styles.inlineRow}>
              <View style={styles.inlineField}>
                <Field
                  label="City"
                  onChangeText={value =>
                    setForm(current => ({ ...current, city: value }))
                  }
                  placeholder="Ahmedabad"
                  styles={styles}
                  theme={theme}
                  value={form.city}
                />
              </View>
              <View style={styles.inlineField}>
                <Field
                  label="State"
                  onChangeText={value =>
                    setForm(current => ({ ...current, state: value }))
                  }
                  placeholder="Gujarat"
                  styles={styles}
                  theme={theme}
                  value={form.state}
                />
              </View>
            </View>
            <View style={styles.inlineRow}>
              <View style={styles.inlineField}>
                <Field
                  keyboardType="number-pad"
                  label="Postal code"
                  onChangeText={value =>
                    setForm(current => ({ ...current, postalCode: value }))
                  }
                  placeholder="380009"
                  styles={styles}
                  theme={theme}
                  value={form.postalCode}
                />
              </View>
              <View style={styles.inlineField}>
                <Field
                  keyboardType="phone-pad"
                  label="Phone number"
                  onChangeText={value =>
                    setForm(current => ({ ...current, phoneNumber: value }))
                  }
                  placeholder="9876543210"
                  styles={styles}
                  theme={theme}
                  value={form.phoneNumber}
                />
              </View>
            </View>
          </View>

          <View style={styles.defaultCard}>
            <View style={styles.defaultCopy}>
              <View style={styles.defaultIcon}>
                <Icon
                  color={theme.colors.success}
                  name="checkmark-circle"
                  size={18}
                />
              </View>
              <View style={styles.defaultTextWrap}>
                <Text style={styles.defaultTitle}>Use as default address</Text>
                <Text style={styles.defaultText}>
                  This address will be selected automatically for delivery.
                </Text>
              </View>
            </View>
            <Switch
              onValueChange={value =>
                setForm(current => ({ ...current, isDefault: value }))
              }
              thumbColor={
                form.isDefault ? theme.colors.primary : theme.colors.white
              }
              trackColor={{
                false: theme.colors.border,
                true: theme.colors.primarySoft,
              }}
              value={form.isDefault}
            />
          </View>
        </ScrollView>

        <View style={styles.footer}>
          <Pressable
            disabled={saving || loading}
            onPress={save}
            style={[
              styles.saveButton,
              (saving || loading) && styles.saveButtonDisabled,
            ]}
          >
            <Text style={styles.saveButtonText}>
              {saving
                ? 'Saving...'
                : route.params.mode === 'edit'
                ? 'Save address'
                : 'Add address'}
            </Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Field({
  label,
  value,
  onChangeText,
  placeholder,
  styles,
  theme,
  keyboardType,
  multiline,
}: {
  label: string;
  value: string;
  onChangeText: (value: string) => void;
  placeholder: string;
  styles: ReturnType<typeof createStyles>;
  theme: AppTheme;
  keyboardType?: 'default' | 'phone-pad' | 'number-pad';
  multiline?: boolean;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <TextInput
        keyboardType={keyboardType}
        multiline={multiline}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={theme.colors.hint}
        style={[styles.input, multiline ? styles.multilineInput : null]}
        textAlignVertical={multiline ? 'top' : 'center'}
        value={value}
      />
    </View>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: { flex: 1, backgroundColor: theme.colors.background },
    flex: { flex: 1 },
    content: {
      padding: theme.spacing.screen,
      paddingTop: theme.spacing.stackTop,
      paddingBottom: 120,
      gap: 16,
    },
    hero: {
      gap: 6,
    },
    heading: {
      color: theme.colors.text,
      fontSize: 24,
      fontWeight: '800',
    },
    helper: {
      color: theme.colors.secondaryText,
      lineHeight: 20,
    },
    labelRow: {
      flexDirection: 'row',
      gap: 10,
    },
    labelChip: {
      flex: 1,
      minHeight: 44,
      borderRadius: 16,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      alignItems: 'center',
      justifyContent: 'center',
    },
    labelChipActive: {
      borderColor: theme.colors.primary,
      backgroundColor: theme.colors.primarySoft,
    },
    labelChipText: {
      color: theme.colors.secondaryText,
      fontWeight: '800',
    },
    labelChipTextActive: {
      color: theme.colors.primary,
    },
    card: {
      borderRadius: 24,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      padding: 18,
      gap: 14,
    },
    field: {
      gap: 8,
    },
    fieldLabel: {
      color: theme.colors.text,
      fontSize: 13,
      fontWeight: '700',
    },
    input: {
      minHeight: 52,
      borderRadius: 16,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surface,
      paddingHorizontal: 14,
      color: theme.colors.text,
    },
    multilineInput: {
      minHeight: 92,
      paddingTop: 14,
    },
    inlineRow: {
      flexDirection: 'row',
      gap: 12,
    },
    inlineField: {
      flex: 1,
    },
    defaultCard: {
      borderRadius: 22,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: theme.colors.border,
      paddingHorizontal: 16,
      paddingVertical: 14,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 14,
    },
    defaultCopy: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      flex: 1,
    },
    defaultIcon: {
      width: 36,
      height: 36,
      borderRadius: 18,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.successSoft,
    },
    defaultTextWrap: {
      flex: 1,
      gap: 2,
    },
    defaultTitle: {
      color: theme.colors.text,
      fontWeight: '800',
    },
    defaultText: {
      color: theme.colors.secondaryText,
      lineHeight: 18,
    },
    footer: {
      paddingHorizontal: theme.spacing.screen,
      paddingBottom: 12,
    },
    saveButton: {
      minHeight: 54,
      borderRadius: 18,
      backgroundColor: theme.colors.primary,
      alignItems: 'center',
      justifyContent: 'center',
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.18,
      shadowRadius: 16,
      shadowOffset: { width: 0, height: 8 },
      elevation: 4,
    },
    saveButtonDisabled: {
      opacity: 0.7,
    },
    saveButtonText: {
      color: theme.colors.onPrimary,
      fontSize: 16,
      fontWeight: '800',
    },
  });
