import React from 'react';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';

// While the saved session is read. Brief, but without it a signed-in tablet
// would flash the login screen on every launch.
export const AppSplashScreen = () => {
  const { colors } = useTheme();
  return (
    <View style={[styles.container, { backgroundColor: colors.background }]}>
      <View style={[styles.mark, { backgroundColor: colors.accent }]}>
        <Text style={[styles.markText, { color: colors.onAccent }]}>K</Text>
      </View>
      <ActivityIndicator color={colors.textMuted} />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 24 },
  mark: {
    width: 72,
    height: 72,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markText: { fontSize: 36, fontWeight: '800' },
});
