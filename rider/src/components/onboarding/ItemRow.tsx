import React from 'react';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Icon, type IconName } from '@components/ui/Icon';
import { Pill } from '@components/ui/Pill';
import { useI18n } from '@/i18n';
import type { ApplicationItem, ItemKind } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';
import type { ItemState } from '@utils/onboarding';

const ICON: Record<ItemKind, IconName> = {
  PERSONAL: 'person-outline',
  SELFIE: 'happy-outline',
  VEHICLE_DETAILS: 'bicycle-outline',
  RC: 'document-text-outline',
  AADHAAR_FRONT: 'card-outline',
  AADHAAR_BACK: 'card-outline',
  PAN: 'card-outline',
  LICENCE_FRONT: 'id-card-outline',
  LICENCE_BACK: 'id-card-outline',
  BANK_DETAILS: 'business-outline',
  BANK_PROOF: 'receipt-outline',
};

const PILL: Record<ItemState, 'neutral' | 'primary' | 'success' | 'danger'> = {
  todo: 'neutral',
  added: 'primary',
  inReview: 'primary',
  accepted: 'success',
  fix: 'danger',
};

/**
 * One thing the application needs, and where it stands. A flagged row is the
 * point of the screen after a send-back: red, with the admin's own words and
 * a Fix that opens the step it lives on.
 */
export function ItemRow({
  kind,
  item,
  state,
  onFix,
}: {
  kind: ItemKind;
  item: ApplicationItem | undefined;
  state: ItemState;
  onFix?: () => void;
}) {
  const { colors } = useTheme();
  const { t } = useI18n();
  const flagged = state === 'fix';
  const ink = flagged
    ? colors.danger
    : state === 'accepted'
    ? colors.success
    : colors.textMuted;

  return (
    <View style={styles.row}>
      <View style={styles.line}>
        <View
          style={[
            styles.icon,
            {
              backgroundColor: flagged ? colors.dangerSoft : colors.surfaceAlt,
            },
          ]}
        >
          <Icon
            name={state === 'accepted' ? 'checkmark' : ICON[kind]}
            size={18}
            color={ink}
          />
        </View>
        <AppText variant="bodyStrong" style={styles.flex}>
          {t(`onboarding.item.${kind}`)}
        </AppText>
        <Pill label={t(`onboarding.state.${state}`)} tone={PILL[state]} />
      </View>
      {flagged ? (
        <View style={styles.flag}>
          {item?.reason ? (
            <AppText variant="label" tone="danger" style={styles.flex}>
              {item.reason}
            </AppText>
          ) : (
            <View style={styles.flex} />
          )}
          {onFix ? (
            <Button
              kind="danger"
              size="md"
              icon="construct-outline"
              label={t('onboarding.home.fix')}
              onPress={onFix}
            />
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    gap: space.sm,
  },
  line: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    minHeight: 40,
  },
  icon: {
    width: 36,
    height: 36,
    borderRadius: 18,
    alignItems: 'center',
    justifyContent: 'center',
  },
  flex: { flex: 1 },
  flag: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingLeft: 36 + space.md,
  },
});
