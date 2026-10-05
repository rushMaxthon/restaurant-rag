// react-native-vector-icons 10 ships no TypeScript types. Only the one family
// this app uses is declared; `components/Icon.tsx` narrows the glyph names.
declare module 'react-native-vector-icons/Ionicons' {
  import type { ComponentType } from 'react';
  import type { StyleProp, TextStyle } from 'react-native';

  const Ionicons: ComponentType<{
    name: string;
    size?: number;
    color?: string;
    style?: StyleProp<TextStyle>;
  }>;
  export default Ionicons;
}
