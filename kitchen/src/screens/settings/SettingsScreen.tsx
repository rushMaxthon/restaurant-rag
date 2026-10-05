import React from 'react';
import { Alert, Pressable, ScrollView, Switch, Text, View } from 'react-native';
import { API_BASE_URL } from '@/config/api';
import { useTheme, useThemedStyles } from '@/theme';
import type { BoardRole, RealtimeStatus } from '@/types/app';
import { ScreenContainer } from '@components/ScreenContainer';
import { ScreenHeader } from '@components/ScreenHeader';
import { Icon } from '@components/Icon';
import { LiveIndicator } from '@components/LiveIndicator';
import { Pill } from '@components/Pill';
import { Skeleton } from '@components/Skeleton';
import { useRealtimeStatus } from '@components/realtime/RealtimeProvider';
import { useAppActions, useBoardScope, usePreferences, useSession } from '@hooks/useAppStore';
import { useRestaurant } from '@hooks/useRestaurant';
import useNavigationHook from '@navigation/hooks/useNavigation';
import { playNewOrderAlert } from '@services/sound';
import { createStyles } from './styles';

const ROLE_LABEL: Record<BoardRole, string> = {
  KITCHEN: 'Kitchen staff',
  OWNER: 'Restaurant owner',
  ADMIN: 'Platform admin',
};

const CONNECTION_COPY: Record<RealtimeStatus, { title: string; body: string }> = {
  live: {
    title: 'Live',
    body: 'New orders appear the moment they are placed.',
  },
  connecting: {
    title: 'Connecting…',
    body: 'Checking for orders every few seconds meanwhile.',
  },
  offline: {
    title: 'Reconnecting',
    body: 'The live connection dropped. The board checks for orders every few seconds until it is back.',
  },
  disabled: {
    title: 'Polling',
    body: 'Live updates are switched off on the server, so the board checks for orders every few seconds.',
  },
};

const initials = (name: string): string =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0]?.toUpperCase() ?? '')
    .join('') || '?';

const SettingsScreen = () => {
  const styles = useThemedStyles(createStyles);
  const { colors } = useTheme();
  const navigation = useNavigationHook();
  const session = useSession();
  const scope = useBoardScope();
  const { soundOn, branchId } = usePreferences();
  const { setSoundOn, setBranchId, signOut } = useAppActions();
  const realtime = useRealtimeStatus();
  const restaurant = useRestaurant(scope.restaurantId);

  if (!session) {
    return null;
  }

  const pinned = session.restaurantLocationId;
  const pinnedBranch = restaurant?.locations.find(location => location.id === pinned);
  const connection = CONNECTION_COPY[realtime ?? 'connecting'];

  const confirmSignOut = () =>
    Alert.alert(
      'Sign out of this tablet?',
      'The board stops showing orders until someone signs in again.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Sign out', style: 'destructive', onPress: () => signOut() },
      ],
    );

  const branchRow = (id: string | null, title: string, isOpen?: boolean, first = false) => {
    const selected = (branchId ?? null) === id;
    return (
      <Pressable
        key={id ?? 'all'}
        testID={`branch-${id ?? 'all'}`}
        onPress={() => setBranchId(id)}
        accessibilityRole="radio"
        accessibilityState={{ selected }}
        style={({ pressed }) => [
          styles.row,
          !first && styles.rowDivider,
          selected && { backgroundColor: colors.accentSoft },
          pressed && { opacity: 0.7 },
        ]}>
        <View style={styles.rowText}>
          <Text style={styles.rowTitle}>{title}</Text>
        </View>
        {isOpen === undefined ? null : (
          <Pill
            label={isOpen ? 'Open' : 'Closed'}
            color={isOpen ? colors.accent : colors.textMuted}
            background={isOpen ? colors.accentSoft : colors.surfaceMuted}
          />
        )}
        {selected ? <Icon name="checkmark" size={22} color={colors.accent} /> : null}
      </Pressable>
    );
  };

  return (
    <ScreenContainer>
      <ScreenHeader title="Settings" onBack={navigation.goBack} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.column}>
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Signed in</Text>
            <View style={styles.group}>
              <View style={styles.row}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{initials(session.user.fullName)}</Text>
                </View>
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>{session.user.fullName}</Text>
                  <Text style={styles.rowBody}>{session.user.email}</Text>
                </View>
                <Pill
                  label={ROLE_LABEL[session.user.role]}
                  color={colors.text}
                  background={colors.surfaceMuted}
                />
              </View>
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Kitchen</Text>
            <View style={styles.group}>
              <View style={styles.row}>
                <Icon name="storefront-outline" size={22} color={colors.textMuted} />
                <View style={styles.rowText}>
                  <Text style={styles.rowBody}>Restaurant</Text>
                  {restaurant ? (
                    <Text style={styles.rowTitle}>{restaurant.name}</Text>
                  ) : (
                    <Skeleton height={20} width={160} radius={6} />
                  )}
                </View>
              </View>
              {pinned ? (
                <View style={[styles.row, styles.rowDivider]}>
                  <Icon name="location-outline" size={22} color={colors.textMuted} />
                  <View style={styles.rowText}>
                    <Text style={styles.rowBody}>Branch</Text>
                    <Text style={styles.rowTitle}>{pinnedBranch?.branch_name ?? '…'}</Text>
                  </View>
                </View>
              ) : null}
            </View>
            {pinned ? (
              <Text style={styles.footnote}>
                This account is assigned to one branch. Only the owner can change that, from the
                admin panel.
              </Text>
            ) : null}
          </View>

          {scope.canChooseBranch ? (
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>Show orders from</Text>
              <View style={styles.group}>
                {branchRow(null, 'All branches', undefined, true)}
                {(restaurant?.locations ?? []).map(location =>
                  branchRow(location.id, location.branch_name, location.is_open),
                )}
              </View>
              <Text style={styles.footnote}>
                Remembered on this tablet. A board set to one branch shows only that branch’s
                orders and completed history.
              </Text>
            </View>
          ) : null}

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Alerts</Text>
            <View style={styles.group}>
              <View style={styles.row}>
                <Icon
                  name={soundOn ? 'volume-high' : 'volume-mute'}
                  size={22}
                  color={colors.textMuted}
                />
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>New order sound</Text>
                  <Text style={styles.rowBody}>
                    A chime and a buzz when an order arrives. Plays even with the tablet on silent.
                  </Text>
                </View>
                <Switch
                  testID="sound-switch"
                  value={soundOn}
                  onValueChange={setSoundOn}
                  trackColor={{ true: colors.accent, false: colors.border }}
                  accessibilityLabel="New order sound"
                />
              </View>
              <View style={[styles.row, styles.rowDivider]}>
                <Icon name="notifications-outline" size={22} color={colors.textMuted} />
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>Check the volume</Text>
                  <Text style={styles.rowBody}>Plays the alert once, now.</Text>
                </View>
                <Pressable
                  onPress={playNewOrderAlert}
                  accessibilityRole="button"
                  style={({ pressed }) => [styles.testButton, pressed && { opacity: 0.7 }]}>
                  <Text style={styles.testButtonText}>Test alert</Text>
                </Pressable>
              </View>
            </View>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Connection</Text>
            <View style={styles.group}>
              <View style={styles.row}>
                <View style={styles.rowText}>
                  <Text style={styles.rowTitle}>{connection.title}</Text>
                  <Text style={styles.rowBody}>{connection.body}</Text>
                </View>
                <LiveIndicator state={realtime === 'live' ? 'live' : 'polling'} />
              </View>
              <View style={[styles.row, styles.rowDivider]}>
                <View style={styles.rowText}>
                  <Text style={styles.rowBody}>Server</Text>
                  <Text selectable style={styles.rowTitle}>
                    {API_BASE_URL}
                  </Text>
                </View>
              </View>
            </View>
          </View>

          <Pressable
            testID="sign-out"
            onPress={confirmSignOut}
            accessibilityRole="button"
            style={({ pressed }) => [styles.signOut, pressed && { opacity: 0.7 }]}>
            <Icon name="log-out-outline" size={22} color={colors.danger} />
            <Text style={styles.signOutText}>Sign out</Text>
          </Pressable>
        </View>
      </ScrollView>
    </ScreenContainer>
  );
};

export default SettingsScreen;
