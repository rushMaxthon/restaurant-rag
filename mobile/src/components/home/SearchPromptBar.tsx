import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { theme, useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface SearchPromptBarProps {
  value?: string;
  onChangeText?: (value: string) => void;
  onFocus?: () => void;
  onBlur?: () => void;
  suggestions?: string[];
  focused?: boolean;
  onSuggestionPress?: (value: string) => void;
  onPress?: () => void;
  readOnly?: boolean;
  placeholder?: string;
}

function SearchPromptBarComponent({
  value = '',
  onChangeText,
  onFocus,
  onBlur,
  suggestions = [],
  focused = false,
  onSuggestionPress,
  onPress,
  readOnly = false,
  placeholder = 'Try: spicy Chinese under ₹200',
}: SearchPromptBarProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const bar = (
    <View style={[styles.bar, focused ? styles.barFocused : null]}>
      <Icon color={theme.colors.hint} name="search" size={20} />
      {readOnly ? (
        <Pressable
          onPress={onPress}
          style={({ pressed }) => [
            styles.pressableInput,
            pressed ? styles.pressableInputPressed : null,
          ]}
        >
          <Text
            numberOfLines={1}
            style={value ? styles.inputText : styles.placeholderText}
          >
            {value || placeholder}
          </Text>
        </Pressable>
      ) : (
        <TextInput
          onBlur={onBlur}
          onChangeText={onChangeText}
          onFocus={onFocus}
          placeholder={placeholder}
          placeholderTextColor={theme.colors.hint}
          style={styles.input}
          value={value}
        />
      )}
      <Pressable onPress={onPress} style={styles.voiceButton}>
        <Icon color={theme.colors.primary} name="mic-outline" size={18} />
      </Pressable>
    </View>
  );

  return (
    <View style={styles.wrap}>
      {bar}
      {focused && suggestions.length > 0 ? (
        <View style={styles.dropdown}>
          {suggestions.map(suggestion => (
            <Pressable
              key={suggestion}
              onPress={() => onSuggestionPress?.(suggestion)}
              style={styles.suggestion}
            >
              <Icon
                color={theme.colors.hint}
                name="sparkles-outline"
                size={16}
              />
              <Text style={styles.suggestionText}>{suggestion}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    wrap: {
      gap: theme.spacing.sm,
      zIndex: 5,
    },
    bar: {
      minHeight: 50,
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      borderWidth: 1,
      borderColor: 'rgba(255,255,255,0.18)',
      paddingHorizontal: 16,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 12,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.1,
      shadowOffset: { width: 0, height: 10 },
      shadowRadius: 18,
      elevation: 4,
    },
    barFocused: {
      borderColor: theme.colors.primary,
    },
    input: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 15,
      paddingVertical: 0,
    },
    pressableInput: {
      flex: 1,
      justifyContent: 'center',
      minHeight: 40,
    },
    pressableInputPressed: {
      opacity: 0.72,
    },
    inputText: {
      color: theme.colors.text,
      fontSize: 15,
    },
    placeholderText: {
      color: theme.colors.hint,
      fontSize: 15,
    },
    voiceButton: {
      width: 34,
      height: 34,
      borderRadius: 17,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    dropdown: {
      borderRadius: 18,
      backgroundColor: theme.colors.surfaceRaised,
      padding: 8,
      shadowColor: theme.colors.shadow,
      shadowOpacity: 0.12,
      shadowOffset: { width: 0, height: 12 },
      shadowRadius: 18,
      elevation: 5,
    },
    suggestion: {
      flexDirection: 'row',
      alignItems: 'center',
      gap: 10,
      paddingHorizontal: 12,
      paddingVertical: 12,
      borderRadius: 14,
    },
    suggestionText: {
      flex: 1,
      color: theme.colors.text,
      fontSize: 14,
    },
  });

const styles = createStyles(theme);

/**
 * Memoized: these cards sit in lists whose parent re-renders on unrelated
 * state changes, and none of them depend on anything but their props.
 */
export const SearchPromptBar = React.memo(SearchPromptBarComponent);
