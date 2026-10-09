import React from 'react';
import { translate } from '@/i18n/translate';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import Animated, {
  FadeIn,
  FadeOut,
  SlideInDown,
  SlideOutDown,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@theme/ThemeProvider';
import { radius, space } from '@theme/tokens';
import { AppText } from './AppText';
import { IconButton } from './IconButton';

/**
 * A sheet from the bottom with a title and whatever the caller puts in it.
 * Controlled by `open`, so a screen keeps one boolean rather than a ref.
 *
 * Built on RN's own Modal rather than a gesture-driven sheet library: the
 * modal is a native window above every screen, so it needs no portal host
 * and nothing to measure, and a tap on the dark backdrop, the close button
 * or the phone's back button closes it. Rider sheets hold three or four
 * choices; a drag handle would be decoration.
 */
export function Sheet({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <Modal
      visible={open}
      transparent
      statusBarTranslucent
      navigationBarTranslucent
      animationType="none"
      onRequestClose={onClose}
    >
      <View style={styles.root}>
        <Animated.View
          entering={FadeIn.duration(180)}
          exiting={FadeOut.duration(150)}
          style={StyleSheet.absoluteFill}
        >
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={translate('common.close')}
            onPress={onClose}
            style={[StyleSheet.absoluteFill, { backgroundColor: colors.overlay }]}
          />
        </Animated.View>
        <Animated.View
          entering={SlideInDown.duration(260)}
          exiting={SlideOutDown.duration(200)}
          style={[
            styles.sheet,
            {
              backgroundColor: colors.elevated,
              borderColor: colors.border,
              paddingBottom: insets.bottom + space.lg,
            },
          ]}
        >
          <View style={[styles.handle, { backgroundColor: colors.textFaint }]} />
          <View style={styles.head}>
            <AppText variant="heading" style={styles.title}>
              {title}
            </AppText>
            <IconButton icon="close" label={translate('common.close')} onPress={onClose} />
          </View>
          <View style={styles.body}>{children}</View>
        </Animated.View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: 'flex-end' },
  sheet: {
    borderTopLeftRadius: radius.xxl,
    borderTopRightRadius: radius.xxl,
    borderWidth: 1,
    paddingHorizontal: space.lg,
    paddingTop: space.sm,
  },
  handle: {
    alignSelf: 'center',
    width: 40,
    height: 4,
    borderRadius: 2,
    marginBottom: space.sm,
    opacity: 0.6,
  },
  head: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.sm,
    marginBottom: space.md,
  },
  title: { flex: 1 },
  body: { gap: space.sm },
});
