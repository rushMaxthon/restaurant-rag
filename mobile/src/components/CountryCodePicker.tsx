import React, { useCallback, useMemo, useState } from 'react';
import {
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  type ListRenderItem,
} from 'react-native';
import { COUNTRIES, type CountryOption } from '@/data/countries';
import { getCountryFlagEmoji } from '@/utils/phoneNumber';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

type Props = {
  selectedCountry: CountryOption;
  onSelect: (country: CountryOption) => void;
};

export function CountryCodePicker({
  selectedCountry,
  onSelect,
}: Props): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const [visible, setVisible] = useState(false);
  const [query, setQuery] = useState('');

  const filteredCountries = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      return COUNTRIES;
    }
    return COUNTRIES.filter(
      country =>
        country.name.toLowerCase().includes(normalizedQuery) ||
        country.dialCode.includes(normalizedQuery) ||
        country.code.toLowerCase().includes(normalizedQuery),
    );
  }, [query]);

  const close = useCallback(() => {
    setVisible(false);
    setQuery('');
  }, []);

  // Hoisted out of the JSX: as an inline prop this row was rebuilt for every
  // country on each keystroke in the search field.
  const renderCountry = useCallback<ListRenderItem<CountryOption>>(
    ({ item }) => {
      const selected = item.code === selectedCountry.code;
      return (
        <Pressable
          onPress={() => {
            onSelect(item);
            close();
          }}
          style={[
            styles.countryRow,
            selected ? styles.countryRowSelected : null,
          ]}
        >
          <Text style={styles.flag}>{getCountryFlagEmoji(item.code)}</Text>
          <View style={styles.countryCopy}>
            <Text style={styles.countryName}>{item.name}</Text>
            <Text style={styles.countryCodeText}>{item.dialCode}</Text>
          </View>
        </Pressable>
      );
    },
    [close, onSelect, selectedCountry.code, styles],
  );

  return (
    <>
      <Pressable onPress={() => setVisible(true)} style={styles.trigger}>
        <Text style={styles.flag}>
          {getCountryFlagEmoji(selectedCountry.code)}
        </Text>
        <Text style={styles.code}>{selectedCountry.dialCode}</Text>
        <Text style={styles.chevron}>▾</Text>
      </Pressable>

      <Modal
        animationType="slide"
        onRequestClose={close}
        transparent
        visible={visible}
      >
        <Pressable onPress={close} style={styles.backdrop}>
          <Pressable onPress={() => null} style={styles.sheet}>
            <Text style={styles.sheetTitle}>Select country code</Text>
            <TextInput
              autoCapitalize="none"
              autoCorrect={false}
              onChangeText={setQuery}
              placeholder="Search country or code"
              placeholderTextColor={theme.colors.hint}
              style={styles.searchInput}
              value={query}
            />
            <FlatList
              data={filteredCountries}
              keyExtractor={item => item.code}
              keyboardShouldPersistTaps="handled"
              renderItem={renderCountry}
              showsVerticalScrollIndicator={false}
            />
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    trigger: {
      minHeight: 50,
      minWidth: 102,
      paddingHorizontal: 12,
      borderRadius: 10,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.background,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'center',
      gap: 6,
    },
    flag: {
      fontSize: 17,
    },
    code: {
      color: theme.colors.text,
      fontSize: 14,
      fontWeight: '800',
    },
    chevron: {
      color: theme.colors.hint,
      fontSize: 12,
      marginTop: 1,
    },
    backdrop: {
      flex: 1,
      backgroundColor:
        theme.mode === 'dark' ? 'rgba(6,10,18,0.72)' : 'rgba(15,23,42,0.32)',
      justifyContent: 'flex-end',
    },
    sheet: {
      maxHeight: '78%',
      borderTopLeftRadius: 24,
      borderTopRightRadius: 24,
      backgroundColor: theme.colors.surface,
      paddingHorizontal: 18,
      paddingTop: 18,
      paddingBottom: 24,
      gap: 14,
    },
    sheetTitle: {
      color: theme.colors.text,
      fontSize: 18,
      fontWeight: '800',
    },
    searchInput: {
      minHeight: 48,
      borderRadius: 12,
      borderWidth: 1,
      borderColor: theme.colors.border,
      backgroundColor: theme.colors.surfaceRaised,
      paddingHorizontal: 14,
      color: theme.colors.text,
      fontSize: 15,
    },
    countryRow: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      borderRadius: 14,
      paddingHorizontal: 12,
      paddingVertical: 12,
    },
    countryRowSelected: {
      backgroundColor: theme.colors.primarySoft,
    },
    countryCopy: {
      flex: 1,
      flexDirection: 'row',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: 12,
    },
    countryName: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 15,
      fontWeight: '600',
    },
    countryCodeText: {
      color: theme.colors.secondaryText,
      fontSize: 14,
      fontWeight: '700',
    },
  });

const styles = createStyles(theme);
