import React from 'react';
import { Ionicons } from '@react-native-vector-icons/ionicons/static';

export type IconName = React.ComponentProps<typeof Ionicons>['name'];

export function Icon({ name, size = 22, color }: { name: IconName; size?: number; color: string }) {
  return <Ionicons name={name} size={size} color={color} />;
}
