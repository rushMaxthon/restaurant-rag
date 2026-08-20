declare module 'react-native-vector-icons/Ionicons' {
  import type {ComponentType} from 'react';

  interface IoniconsProps {
    name: string;
    size?: number;
    color?: string;
  }

  const Ionicons: ComponentType<IoniconsProps>;
  export default Ionicons;
}
