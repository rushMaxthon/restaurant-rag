import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Ionicons';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

interface AppHeaderProps {
  title: string;
  canGoBack?: boolean;
  onBack?: () => void;
  /** Screens opt into a trailing action by setting `headerRight`. */
  right?: React.ReactNode;
}

export function AppHeader({
  title,
  canGoBack = false,
  onBack,
  right,
}: AppHeaderProps): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  return (
    <SafeAreaView edges={['top']} style={styles.safeArea}>
      <View style={styles.row}>
        <View style={styles.side}>
          {canGoBack ? (
            <Pressable hitSlop={10} onPress={onBack} style={styles.backButton}>
              <Icon color={theme.colors.text} name="arrow-back" size={20} />
            </Pressable>
          ) : null}
        </View>
        <View style={styles.center}>
          <Text numberOfLines={1} style={styles.title}>
            {title}
          </Text>
        </View>
        <View style={[styles.side, styles.sideRight]}>{right}</View>
      </View>
    </SafeAreaView>
  );
}

const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: {
      backgroundColor: theme.colors.background,
      borderBottomWidth: 1,
      borderBottomColor: theme.colors.divider,
    },
    row: {
      minHeight: 56,
      flexDirection: 'row',
      alignItems: 'center',
      paddingHorizontal: theme.spacing.screen,
    },
    side: {
      width: 44,
      alignItems: 'flex-start',
      justifyContent: 'center',
    },
    sideRight: {
      alignItems: 'flex-end',
    },
    center: {
      flex: 1,
      alignItems: 'center',
      justifyContent: 'center',
      paddingHorizontal: 12,
    },
    backButton: {
      width: 40,
      height: 40,
      borderRadius: 20,
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: theme.colors.surface,
    },
    title: {
      color: theme.colors.text,
      fontSize: 17,
      fontWeight: '800',
      textAlign: 'center',
    },
  });

