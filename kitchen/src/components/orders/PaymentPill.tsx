import React from 'react';
import { Pill } from '@components/Pill';
import { useTheme } from '@/theme';
import { payKind } from '@utils/board';

// Cash owed is the loud one: it changes what happens at the hand-over. Paid
// is stated once and quietly.
export const PaymentPill = ({ status, label }: { status: string; label: string }) => {
  const { colors } = useTheme();
  const kind = payKind(status);
  if (kind === 'COD') {
    return (
      <Pill label={label} icon="cash-outline" color={colors.warning} background={colors.warningSoft} />
    );
  }
  if (kind === 'PAID') {
    return (
      <Pill label={label} icon="checkmark" color={colors.accent} background={colors.accentSoft} />
    );
  }
  return (
    <Pill label={label} icon="alert-circle" color={colors.danger} background={colors.dangerSoft} />
  );
};
