import React from 'react';
import { StyleSheet, View } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { useTheme } from '@theme/ThemeProvider';
import { Icon } from './Icon';

/** The app's mark: a warm gradient tile with a bike, drawn (no image asset to load). */
export function BrandMark({ size = 72 }: { size?: number }) {
  const { colors } = useTheme();
  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size} style={StyleSheet.absoluteFill}>
        <Defs>
          <LinearGradient id="g" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor="#FF7A3D" />
            <Stop offset="1" stopColor={colors.primary} />
          </LinearGradient>
        </Defs>
        <Rect x={0} y={0} width={size} height={size} rx={size * 0.28} fill="url(#g)" />
      </Svg>
      <View style={styles.center}>
        <Icon name="bicycle" size={size * 0.55} color="#FFFFFF" />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, alignItems: 'center', justifyContent: 'center' },
});
