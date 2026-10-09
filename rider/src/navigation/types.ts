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

/** What a phone code is for: making an account, or a forgotten password. */
export type CodePurpose = 'signup' | 'reset';

export type RootStackParamList = {
  Login: undefined;
  // Signing up (signed out)
  /** `purpose: 'reset'` is forgot-password: the same two screens, a code to an existing account. */
  SignupPhone: { phone?: string; purpose?: CodePurpose } | undefined;
  SignupCode: {
    phone: string;
    purpose?: CodePurpose;
    debugCode: string | null;
    retryAfter: number;
    /** Back from the account screen: the code was refused. `errorAt` makes the same error twice still land. */
    error?: string;
    errorAt?: number;
  };
  SignupAccount: { phone: string; code: string };
  ResetPassword: { phone: string; code: string };
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
