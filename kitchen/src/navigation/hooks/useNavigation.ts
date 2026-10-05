import {
  type NavigationProp,
  type RouteProp,
  useNavigation,
  useRoute,
} from '@react-navigation/native';
import type { KitchenOrder } from '@/types/app';

export type RootStackParamList = {
  LoginScreen: undefined;
  BoardScreen: undefined;
  OrderDetailScreen: {
    orderId: string;
    // The row that was tapped, so the screen paints at once. It is refetched
    // straight away; this is only the first frame.
    order?: KitchenOrder;
  };
  OrderHistoryScreen: undefined;
  SettingsScreen: undefined;
};

const useNavigationHook = () => {
  return useNavigation<NavigationProp<RootStackParamList>>();
};

export const useRouteHook = <T extends keyof RootStackParamList>() => {
  return useRoute<RouteProp<RootStackParamList, T>>();
};

export default useNavigationHook;
