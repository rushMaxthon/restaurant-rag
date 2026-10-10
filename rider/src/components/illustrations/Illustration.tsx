import React, { useMemo } from 'react';
import { View, type StyleProp, type ViewStyle } from 'react-native';
import { SvgXml } from 'react-native-svg';

import { useTheme } from '@theme/ThemeProvider';
import { fillTemplate, illustrationPalette } from './palette';
import { SCENES, type SceneName } from './scenes';

/**
 * One of the app's pictures (`scenes.ts`), in the current theme. 3:2, as
 * wide as asked. Decorative: the words beside it carry the meaning, so a
 * screen reader skips it. Memoised: it sits on screens that re-render
 * with every poll, and an SVG tree is not free to reconcile.
 */
export const Illustration = React.memo(function Illustration({
  name,
  width = 240,
  style,
  palette,
}: {
  name: SceneName;
  width?: number;
  style?: StyleProp<ViewStyle>;
  /** Colours to use instead of the theme's, for a picture on a fixed ground (the splash). */
  palette?: Record<string, string>;
}) {
  const { colors, mode } = useTheme();
  const xml = useMemo(
    () =>
      fillTemplate(SCENES[name], {
        ...illustrationPalette(colors, mode),
        ...palette,
      }),
    [name, colors, mode, palette],
  );
  return (
    <View
      style={[{ width, height: (width * 2) / 3 }, style]}
      accessible={false}
      importantForAccessibility="no-hide-descendants"
    >
      <SvgXml xml={xml} width="100%" height="100%" />
    </View>
  );
});
