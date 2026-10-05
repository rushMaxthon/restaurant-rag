import {
  type NavigationProp,
  type NavigatorScreenParams,
  type RouteProp,
  useNavigation,
  useRoute,
} from '@react-navigation/native';
import type { KitchenOrder } from '@/types/app';

// The two tabs a signed-in tablet lives in.
export type MainTabParamList = {
  BoardScreen: undefined;
  SettingsScreen: undefined;
};

export type RootStackParamList = {
  LoginScreen: undefined;
  // The tab bar and both tabs, as one screen of the root stack.
  MainTabs: NavigatorScreenParams<MainTabParamList> | undefined;
  OrderDetailScreen: {
    orderId: string;
    // The row that was tapped, so the screen paints at once. It is refetched
    // straight away; this is only the first frame.
    order?: KitchenOrder;
  };
  OrderHistoryScreen: undefined;
};

// Every route a screen may name. A tab screen navigating to a stack screen
// (Board → Order details) bubbles up to the root stack; one switching tabs
// (Board → Settings) is handled by the tab navigator it sits in.
export type AppParamList = RootStackParamList & MainTabParamList;

const useNavigationHook = () => {
  return useNavigation<NavigationProp<AppParamList>>();
};

export const useRouteHook = <T extends keyof AppParamList>() => {
  return useRoute<RouteProp<AppParamList, T>>();
};

export default useNavigationHook;
