import {
  useNavigation,
  type NavigatorScreenParams,
} from '@react-navigation/native';
import type { NativeStackNavigationProp } from '@react-navigation/native-stack';

import type { SectionKey, Trip } from '@/types/api';

export type TabParamList = {
  Home: undefined;
  Orders: undefined;
  Earnings: undefined;
  History: undefined;
  Profile: undefined;
};

export type RootStackParamList = {
  Login: undefined;
  // Signing up (signed out)
  SignupPhone: { phone?: string } | undefined;
  SignupCode: {
    phone: string;
    debugCode: string | null;
    retryAfter: number;
    /** Back from the account screen: the code was refused. `errorAt` makes the same error twice still land. */
    error?: string;
    errorAt?: number;
  };
  SignupAccount: { phone: string; code: string };
  // The application (signed in, not approved yet)
  OnboardingHome: undefined;
  /** `single`: opened from Fix or Edit - saving goes back instead of on to the next step. */
  ApplicationStep: { step: SectionKey; single?: boolean };
  ApplicationReview: undefined;
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
