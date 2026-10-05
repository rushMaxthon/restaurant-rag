import React from 'react';
import type { StyleProp, TextStyle } from 'react-native';
import Ionicons from 'react-native-vector-icons/Ionicons';

// Every glyph this app draws. Narrowed from Ionicons' few thousand so a typo
// is a type error instead of a "?" box on a kitchen wall.
export type IconName =
  | 'fast-food-outline'
  | 'chevron-down'
  | 'wifi'
  | 'speedometer-outline'
  | 'cube-outline'
  | 'ellipse'
  | 'radio-button-on'
  | 'checkmark-done-circle'
  | 'today-outline'
  | 'timer-outline'
  | 'server-outline'
  | 'person-outline'
  | 'arrow-forward'
  | 'alert-circle'
  | 'arrow-back'
  | 'bag-handle-outline'
  | 'bicycle'
  | 'calendar-outline'
  | 'cash-outline'
  | 'checkmark'
  | 'checkmark-circle'
  | 'checkmark-done'
  | 'chevron-forward'
  | 'close-circle'
  | 'cloud-offline-outline'
  | 'file-tray-outline'
  | 'flame'
  | 'home'
  | 'home-outline'
  | 'hourglass-outline'
  | 'information-circle-outline'
  | 'location-outline'
  | 'log-out-outline'
  | 'notifications-outline'
  | 'person-circle-outline'
  | 'play-circle-outline'
  | 'receipt-outline'
  | 'refresh'
  | 'restaurant'
  | 'search'
  | 'settings'
  | 'settings-outline'
  | 'storefront-outline'
  | 'time-outline'
  | 'volume-high'
  | 'volume-mute'
  | 'warning';

interface IconProps {
  name: IconName;
  size?: number;
  color: string;
  style?: StyleProp<TextStyle>;
}

export const Icon = ({ name, size = 20, color, style }: IconProps) => (
  <Ionicons name={name} size={size} color={color} style={style} />
);
