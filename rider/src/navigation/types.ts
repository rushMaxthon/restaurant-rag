import { useNavigation, type NavigatorScreenParams } from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';

export type TabParamList = {
  Home: undefined;
  Earnings: undefined;
  History: undefined;
  Profile: undefined;
};

export type RootStackParamList = {
  Login: undefined;
  Main: NavigatorScreenParams<TabParamList> | undefined;
  Permissions: undefined;
  Offer: undefined;
  Trip: undefined;
  Delivered: { amount: string; orderCode: string };
  Gallery: undefined;
};

export function useNav() {
  return useNavigation<NativeStackNavigationProp<RootStackParamList>>();
}
