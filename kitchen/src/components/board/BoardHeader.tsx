import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useTheme } from '@/theme';
import { Icon } from '@components/Icon';
import { IconButton } from '@components/IconButton';
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
}

// Whose kitchen this is, whether it is current, and the three ways off the
// board. One deployment serves every tenant, so the header always names the
// restaurant and branch: a board that cannot say whose queue it shows is a
// board somebody eventually works the wrong queue from.
export const BoardHeader = ({
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
}: BoardHeaderProps) => {
  const { colors } = useTheme();
  const time = now.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  const date = now.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });

  return (
    <View style={[styles.bar, { borderBottomColor: colors.border }]}>
      <Pressable
        onPress={onOpenSettings}
        accessibilityRole="button"
        accessibilityLabel={`${restaurantName ?? 'Kitchen'}${branchName ? `, ${branchName}` : ''}. Open settings.`}
        style={styles.where}>
        <View style={[styles.mark, { backgroundColor: colors.accent }]}>
          <Icon name="restaurant" size={20} color={colors.onAccent} />
        </View>
        <View style={styles.titles}>
          <Text numberOfLines={1} style={[styles.title, { color: colors.text }]}>
            {restaurantName ?? 'Kitchen'}
          </Text>
          <View style={styles.subRow}>
            {branchName ? (
              <Text numberOfLines={1} style={[styles.branch, { color: colors.textMuted }]}>
                {branchName}
              </Text>
            ) : null}
            {!wide ? <LiveDot state={freshness} /> : null}
          </View>
        </View>
      </Pressable>

      <View style={styles.right}>
        {wide ? (
          <>
            <LiveIndicator state={freshness} />
            {isOpen === undefined ? null : (
              <Pill
                label={isOpen ? 'OPEN' : 'CLOSED'}
                color={isOpen ? colors.accent : colors.danger}
                background={isOpen ? colors.accentSoft : colors.dangerSoft}
                size="md"
              />
            )}
            <View style={styles.clock}>
              <Text style={[styles.time, { color: colors.text }]}>{time}</Text>
              <Text style={[styles.date, { color: colors.textMuted }]}>{date}</Text>
            </View>
          </>
        ) : null}
        <IconButton
          testID="open-history"
          icon="receipt-outline"
          label={wide ? 'Completed' : undefined}
          accessibilityLabel="Completed orders"
          onPress={onOpenHistory}
        />
        <IconButton
          testID="toggle-sound"
          icon={soundOn ? 'volume-high' : 'volume-mute'}
          active={soundOn}
          accessibilityLabel={soundOn ? 'Mute new order alerts' : 'Unmute new order alerts'}
          onPress={onToggleSound}
        />
        <IconButton
          testID="open-settings"
          icon="settings-outline"
          accessibilityLabel="Settings"
          onPress={onOpenSettings}
        />
      </View>
    </View>
  );
};

// The phone header's compact freshness signal: a dot plus a word only when
// something is wrong — "Live" every few seconds is noise on a small screen.
const LiveDot = ({ state }: { state: FreshnessState }) => {
  const { colors } = useTheme();
  const color = state === 'live' ? colors.accent : state === 'stale' ? colors.danger : colors.warning;
  return (
    <View style={styles.dotRow} accessible accessibilityLabel={`Board status: ${state}`}>
      <View style={[styles.dot, { backgroundColor: color }]} />
      {state === 'stale' ? (
        <Text style={[styles.dotText, { color }]}>Not updating</Text>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  where: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 12, minWidth: 0 },
  mark: { width: 44, height: 44, borderRadius: 12, alignItems: 'center', justifyContent: 'center' },
  titles: { flex: 1, minWidth: 0 },
  title: { fontSize: 19, fontWeight: '800' },
  subRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  branch: { fontSize: 14, fontWeight: '600', flexShrink: 1 },
  right: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  clock: { alignItems: 'flex-end', marginHorizontal: 4 },
  time: { fontSize: 20, fontWeight: '800', fontVariant: ['tabular-nums'] },
  date: { fontSize: 12, fontWeight: '600' },
  dotRow: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  dotText: { fontSize: 12, fontWeight: '800' },
});
