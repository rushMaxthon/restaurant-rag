import React from 'react';
import { StyleSheet, View } from 'react-native';

import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Icon } from '@components/ui/Icon';
import { dark } from '@theme/tokens';

type State = { error: Error | null };

/**
 * The last line of defence: a screen that throws shows "Try again" instead
 * of a blank screen a rider cannot get out of. Nothing is lost by retrying -
 * every truth (online, the trip, the steps) is on the server.
 */
export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('Screen crashed', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <View style={[styles.root, { backgroundColor: dark.bg }]}>
        <View style={[styles.icon, { backgroundColor: dark.dangerSoft }]}>
          <Icon name="warning" size={34} color={dark.danger} />
        </View>
        <AppText variant="title" align="center" style={{ color: dark.text }}>
          Something went wrong
        </AppText>
        <AppText align="center" style={[styles.body, { color: dark.textMuted }]}>
          Your delivery and status are safe on the server. Tap below to reload.
        </AppText>
        <Button label="Try again" icon="refresh" onPress={() => this.setState({ error: null })} style={styles.button} />
      </View>
    );
  }
}

const styles = StyleSheet.create({
  root: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  icon: { width: 80, height: 80, borderRadius: 40, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  body: { marginBottom: 16 },
  button: { alignSelf: 'stretch' },
});
