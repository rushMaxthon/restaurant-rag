import React, { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { radius, space, useTheme } from '@/theme';
import { Icon, type IconName } from '@components/Icon';
import { LiveIndicator, type FreshnessState } from '@components/LiveIndicator';
import { Pill } from '@components/Pill';

interface BoardHeaderProps {
  wide: boolean;
  restaurantName: string | null;
  branchName: string | null;
  isOpen: boolean | undefined;
  freshness: FreshnessState;
  now: Date;
  soundOn: boolean;
  onToggleSound: () => void;
  onOpenHistory: () => void;
  onOpenSettings: () => void;
  // Which half to draw. A phone keeps the top bar fixed and lets the title
  // scroll away with the tickets; everywhere else both are drawn together.
  part?: 'all' | 'bar' | 'title';
}

// Two parts. A top bar that says whose kitchen this is — the restaurant and
// branch, tappable through to Settings where the branch is chosen — with the
// board's tools. Then the page title with whether the board is current.
//
// One deployment serves every tenant, so the restaurant and branch are always
// named: a board that cannot say whose queue it shows is a board somebody
// eventually works the wrong queue from.
const BoardHeaderComponent = ({
  wide,
  restaurantName,
  branchName,
  isOpen,
  freshness,
  now,
  soundOn,
  onToggleSound,
  onOpenHistory,
  onOpenSettings,
  part = 'all',
}: BoardHeaderProps) => {
  const { colors } = useTheme();
  const time = now.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  });

  const bar = (
    <View
      style={[
        styles.bar,
        {
          backgroundColor: colors.background,
          borderBottomColor: colors.border,
        },
      ]}
    >
      <Pressable
        testID="board-brand"
        onPress={onOpenSettings}
        accessibilityRole="button"
        accessibilityLabel={`${restaurantName ?? 'Kitchen'}${
          branchName ? `, ${branchName}` : ''
        }. Open settings.`}
        style={({ pressed }) => [styles.brand, pressed && styles.pressed]}
      >
        <View style={[styles.mark, { backgroundColor: colors.accent }]}>
          <Icon name="storefront-outline" size={22} color={colors.onAccent} />
        </View>
        <View style={styles.brandText}>
          <View style={styles.brandRow}>
            <Text
              numberOfLines={1}
              style={[styles.restaurant, { color: colors.text }]}
            >
              {restaurantName ?? 'Kitchen'}
            </Text>
            <Icon name="chevron-forward" size={16} color={colors.text} />
          </View>
          {branchName ? (
            <Text
              numberOfLines={1}
              style={[styles.branch, { color: colors.textMuted }]}
            >
              {branchName}
            </Text>
          ) : null}
        </View>
      </Pressable>
      <View style={styles.tools}>
        <ToolButton
          testID="open-history"
          icon="receipt-outline"
          label={wide ? 'Completed' : undefined}
          accessibilityLabel="Completed orders"
          onPress={onOpenHistory}
        />
        <ToolButton
          testID="toggle-sound"
          icon={soundOn ? 'volume-high' : 'volume-mute'}
          active={soundOn}
          accessibilityLabel={
            soundOn ? 'Mute new order alerts' : 'Unmute new order alerts'
          }
          onPress={onToggleSound}
        />
        <ToolButton
          testID="open-settings"
          icon="settings-outline"
          accessibilityLabel="Settings"
          onPress={onOpenSettings}
        />
      </View>
    </View>
  );

  const title = (
    <View style={styles.titleBlock}>
      <View style={styles.titleText}>
        <Text style={[styles.overline, { color: colors.accent }]}>
          Live order board
        </Text>
        <Text
          accessibilityRole="header"
          style={[styles.title, { color: colors.text }]}
        >
          Kitchen orders
        </Text>
        <Text style={[styles.subtitle, { color: colors.textMuted }]}>
          Keep every order moving, from ticket to handoff.
          {wide ? ` · ${time}` : ''}
        </Text>
      </View>
      <View style={styles.badges}>
        <LiveIndicator state={freshness} />
        {wide && isOpen !== undefined ? (
          <Pill
            label={isOpen ? 'OPEN' : 'CLOSED'}
            color={isOpen ? colors.accent : colors.danger}
            background={isOpen ? colors.accentSoft : colors.dangerSoft}
          />
        ) : null}
      </View>
    </View>
  );

  if (part === 'bar') {
    return bar;
  }
  if (part === 'title') {
    return title;
  }
  return (
    <View>
      {bar}
      {title}
    </View>
  );
};

export const BoardHeader = memo(BoardHeaderComponent);

const ToolButton = ({
  icon,
  label,
  active = false,
  accessibilityLabel,
  onPress,
  testID,
}: {
  icon: IconName;
  label?: string;
  active?: boolean;
  accessibilityLabel: string;
  onPress: () => void;
  testID: string;
}) => {
  const { colors } = useTheme();
  const ink = active ? colors.accent : colors.text;
  return (
    <Pressable
      testID={testID}
      onPress={onPress}
      hitSlop={4}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      accessibilityState={{ selected: active }}
      style={({ pressed }) => [
        styles.tool,
        label ? styles.toolLabelled : null,
        {
          backgroundColor: active ? colors.accentSoft : colors.surface,
          borderColor: active ? colors.accent : colors.border,
        },
        pressed && styles.pressed,
      ]}
    >
      <Icon name={icon} size={20} color={ink} />
      {label ? (
        <Text style={[styles.toolLabel, { color: ink }]}>{label}</Text>
      ) : null}
    </Pressable>
  );
};

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingVertical: space.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  brand: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    minWidth: 0,
  },
  pressed: { opacity: 0.7 },
  mark: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  brandText: { flex: 1, minWidth: 0 },
  brandRow: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  restaurant: { fontSize: 17, fontWeight: '800', flexShrink: 1 },
  branch: { fontSize: 13, fontWeight: '500', marginTop: 1 },
  tools: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  tool: {
    minWidth: 40,
    height: 40,
    borderRadius: radius.md,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    flexDirection: 'row',
    gap: 6,
  },
  toolLabelled: { paddingHorizontal: 12 },
  toolLabel: { fontSize: 14, fontWeight: '700' },
  titleBlock: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingTop: space.lg,
  },
  titleText: { flex: 1, minWidth: 0, gap: 2 },
  overline: {
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  title: { fontSize: 26, fontWeight: '800', letterSpacing: -0.3 },
  subtitle: { fontSize: 14, fontWeight: '500', marginTop: 2 },
  badges: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    paddingBottom: 2,
  },
});
