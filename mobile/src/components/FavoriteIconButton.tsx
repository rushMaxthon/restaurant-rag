import React from 'react';
import { Pressable, StyleSheet } from 'react-native';
import Icon from 'react-native-vector-icons/Ionicons';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface FavoriteIconButtonProps {
  active: boolean;
  disabled?: boolean;
  onPress: () => void;
}

export function FavoriteIconButton({
  active,
  disabled = false,
  onPress,
}: FavoriteIconButtonProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <Pressable
      accessibilityLabel={active ? 'Remove from favorites' : 'Add to favorites'}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        active ? styles.buttonActive : null,
        disabled ? styles.buttonDisabled : null,
        pressed && !disabled ? styles.buttonPressed : null,
      ]}
    >
      <Icon
        color={active ? theme.colors.deepRed : theme.colors.text}
        name={active ? 'heart' : 'heart-outline'}
        size={18}
      />
    </Pressable>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    button: {
      width: 34,
      height: 34,
      borderRadius: 17,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor:
        theme.mode === 'dark'
          ? 'rgba(18, 23, 31, 0.92)'
          : 'rgba(255,255,255,0.92)',
      borderWidth: 1,
      borderColor: theme.colors.border,
    },
    buttonActive: {
      borderColor:
        theme.mode === 'dark'
          ? 'rgba(203, 32, 45, 0.32)'
          : 'rgba(204, 40, 40, 0.18)',
      backgroundColor: theme.colors.dangerSoft,
    },
    buttonDisabled: {
      opacity: 0.55,
    },
    buttonPressed: {
      transform: [{ scale: 0.98 }],
    },
  });

