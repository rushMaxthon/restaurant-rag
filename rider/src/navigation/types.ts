import {
  useNavigation,
  type NavigatorScreenParams,
} from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';

import type { Trip } from '@/types/api';

export type TabParamList = {
  Home: undefined;
  Orders: undefined;
  Earnings: undefined;
  History: undefined;
  Profile: undefined;
};

export type RootStackParamList = {
  Login: undefined;
  Intro: { replay?: boolean } | undefined;
  Main: NavigatorScreenParams<TabParamList> | undefined;
  Permissions: undefined;
  Offer: undefined;
  Trip: undefined;
  Delivered: { amount: string; orderCode: string };
  TripDetail: { trip: Trip };
  Gallery: undefined;
};

export function useNav() {
  return useNavigation<NativeStackNavigationProp<RootStackParamList>>();
}
