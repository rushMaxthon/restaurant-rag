import React, { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { Sheet } from '@components/ui/Sheet';
import { LANGUAGE_NAMES, useI18n } from '@/i18n';
import { useTheme } from '@theme/ThemeProvider';
import { radius, space, touch } from '@theme/tokens';

/** Follow the phone, or one of the three: the list Profile and the button below both open. */
export function LanguageSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const i18n = useI18n();
  const { t } = i18n;
  const { colors } = useTheme();
  return (
    <Sheet open={open} onClose={onClose} title={t('account.language.title')}>
      {(['system', 'en', 'hi', 'gu'] as const).map(option => {
        const active = option === i18n.preference;
        return (
          <Card
            key={option}
            tone={active ? 'primary' : 'surface'}
            style={styles.row}
            onPress={() => {
              i18n.setPreference(option);
              onClose();
            }}
          >
            <View style={styles.flex}>
              <AppText variant="bodyStrong">
                {option === 'system' ? t('account.language.phone') : LANGUAGE_NAMES[option]}
              </AppText>
            </View>
            {active ? <Icon name="checkmark-circle" size={22} color={colors.primary} /> : null}
          </Card>
        );
      })}
    </Sheet>
  );
}

/**
 * A small "English" pill in the corner of the screens a rider sees before
 * Profile exists for them - sign-in, sign-up and the application. Someone
 * who cannot read the current language has to be able to find it, so it
 * shows the language's own name and the translate icon, never a word in it.
 */
export function LanguageButton() {
  const { lang } = useI18n();
  const { colors } = useTheme();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={LANGUAGE_NAMES[lang]}
        hitSlop={8}
        onPress={() => setOpen(true)}
        style={({ pressed }) => [
          styles.pill,
          { backgroundColor: colors.surfaceAlt, borderColor: colors.border, opacity: pressed ? 0.7 : 1 },
        ]}
        testID="language-button"
      >
        <Icon name="language-outline" size={18} color={colors.textMuted} />
        <AppText variant="label">{LANGUAGE_NAMES[lang]}</AppText>
        <Icon name="chevron-down" size={14} color={colors.textMuted} />
      </Pressable>
      <LanguageSheet open={open} onClose={() => setOpen(false)} />
    </>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: space.md },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.xs,
    minHeight: touch.min,
    paddingHorizontal: space.md,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth * 2,
    alignSelf: 'flex-end',
  },
});
