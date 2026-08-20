import type { NavigatorScreenParams } from '@react-navigation/native';
import type { RecommendationItem, Restaurant } from '@/types/app';

export type MainTabParamList = {
  Home: undefined;
  Orders: undefined;
  Chat: undefined;
  Profile: undefined;
};

export type AuthRedirectTarget =
  | {
      screen: 'MainTabs';
      params?: NavigatorScreenParams<MainTabParamList>;
    }
  | {
      screen: 'Restaurant';
      params: {
        restaurantId: string;
        restaurantName: string;
      };
    }
  | {
      screen: 'MenuItemDetail';
      params: {
        itemId: string;
        restaurantId?: string;
        restaurantName?: string;
      };
    }
  | {
      screen: 'Cart';
    }
  | {
      screen: 'OrderList';
    }
  | {
      screen: 'Favorites';
    }
  | {
      screen: 'PersonalizedPicks';
      params?: {
        initialRecommendations?: RecommendationItem[];
      };
    }
  | {
      screen: 'OrderDetail';
      params: {
        orderId: string;
      };
    };

export type RootStackParamList = {
  MainTabs: NavigatorScreenParams<MainTabParamList> | undefined;
  Restaurant: { restaurantId: string; restaurantName: string };
  Restaurants:
    | {
        initialRestaurants?: Restaurant[];
      }
    | undefined;
  MenuItemDetail: {
    itemId: string;
    restaurantId?: string;
    restaurantName?: string;
  };
  PersonalizedPicks:
    | {
        initialRecommendations?: RecommendationItem[];
      }
    | undefined;
  Search: undefined;
  Favorites: undefined;
  Cart: undefined;
  Payment:
    | {
        instructions?: string;
        validatedAt?: string;
        /**
         * An existing unpaid card order to settle. Set when the customer
         * returns to an order that is still awaiting payment, so the retry
         * pays that order instead of creating a second one.
         */
        retryOrderId?: string;
      }
    | undefined;
  OrderSuccess: { orderId?: string } | undefined;
  OrderList: undefined;
  OrderDetail: { orderId: string };
  PreferencesOnboarding: undefined;
  Login:
    | {
        redirectTo?: AuthRedirectTarget;
        prefilledPhoneNumber?: string;
        prefilledCountryCode?: string;
      }
    | undefined;
  Register:
    | {
        redirectTo?: AuthRedirectTarget;
        prefilledPhoneNumber?: string;
        prefilledCountryCode?: string;
      }
    | undefined;
  OtpVerification: {
    localPhoneNumber: string;
    fullPhoneNumber: string;
    countryCode: string;
    countryDialCode: string;
    redirectTo?: AuthRedirectTarget;
  };
  ProfileDetails: undefined;
  UserPreferences: { mode?: 'onboarding' | 'edit' } | undefined;
  SavedAddresses: undefined;
  SavedAddressEditor:
    | {
        mode: 'create';
      }
    | {
        mode: 'edit';
        addressId: string;
      };
  LocationSelect: undefined;
  NotificationSettings: undefined;
  Privacy: undefined;
  Appearance: undefined;
  HelpSupport: undefined;
};
