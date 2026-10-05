import React from 'react';
import { StyleSheet, View } from 'react-native';
import { inkOn } from '@/themePalette';
import { Icon, type IconName } from '@components/Icon';

// A small filled square holding an icon: the leading mark on settings and
// fact rows. Colour carries the row's meaning, so a list can be scanned by
// tile before any label is read.
export const IconTile = ({
  icon,
  color,
  size = 36,
}: {
  icon: IconName;
  color: string;
  size?: number;
}) => (
  <View style={[styles.tile, { width: size, height: size, borderRadius: size * 0.28, backgroundColor: color }]}>
    <Icon name={icon} size={size * 0.55} color={inkOn(color)} />
  </View>
);

const styles = StyleSheet.create({
  tile: { alignItems: 'center', justifyContent: 'center' },
});
