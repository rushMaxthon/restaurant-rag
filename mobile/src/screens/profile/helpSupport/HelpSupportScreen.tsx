import React from 'react';
import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Icon from 'react-native-vector-icons/Ionicons';
import { useTheme, useThemedStyles, type AppTheme } from '@/theme';

export function HelpSupportScreen(): React.JSX.Element {
  const theme = useTheme();
  const styles = useThemedStyles(createStyles);
  const items = [
    {
      icon: 'chatbox-ellipses-outline',
      title: 'Chat support',
      description:
        'Get help with orders, refunds, restaurant issues, and app guidance.',
    },
    {
      icon: 'mail-outline',
      title: 'Email support',
      description: 'support@restaurantrag.app',
    },
    {
      icon: 'call-outline',
      title: 'Phone support',
      description: '+91 1800 000 000',
    },
  ];

  return (
    <SafeAreaView edges={['bottom']} style={styles.safeArea}>
      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.card}>
          <Text style={styles.heading}>Help & support</Text>
          <Text style={styles.helper}>
            If something feels off with your order or your AI assistant
            experience, start here.
          </Text>
          {items.map(item => (
            <View key={item.title} style={styles.row}>
              <View style={styles.iconWrap}>
                <Icon color={theme.colors.primary} name={item.icon} size={18} />
              </View>
              <View style={styles.copy}>
                <Text style={styles.title}>{item.title}</Text>
                <Text style={styles.subtitle}>{item.description}</Text>
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

export const createStyles = (theme: AppTheme) =>
  StyleSheet.create({
    safeArea: { flex: 1, backgroundColor: theme.colors.background },
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
      gap: 16,
    },
    heading: { color: theme.colors.text, fontSize: 22, fontWeight: '800' },
    helper: { color: theme.colors.secondaryText, lineHeight: 20 },
    row: { flexDirection: 'row', gap: 12, alignItems: 'center' },
    iconWrap: {
      width: 42,
      height: 42,
      borderRadius: 21,
      backgroundColor: theme.colors.primarySoft,
      alignItems: 'center',
      justifyContent: 'center',
    },
    copy: { flex: 1, gap: 4 },
    title: { color: theme.colors.text, fontWeight: '800' },
    subtitle: {
      color: theme.colors.secondaryText,
      lineHeight: 18,
      fontSize: 12,
    },
  });
