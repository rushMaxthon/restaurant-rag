import type {NativeStackNavigationProp} from '@react-navigation/native-stack';
import type {
  AuthRedirectTarget,
  RootStackParamList,
} from '@/navigation/navigationTypes';
import type {ToastMessage} from '@/types/app';

interface CheckAuthAndRedirectOptions {
  token: string | null;
  navigation: NativeStackNavigationProp<RootStackParamList>;
  pushToast: (
    title: string,
    description: string,
    tone?: ToastMessage['tone'],
  ) => void;
  redirectTo: AuthRedirectTarget;
}

export function checkAuthAndRedirect({
  token,
  navigation,
  pushToast,
  redirectTo,
}: CheckAuthAndRedirectOptions): boolean {
  if (token) {
    return true;
  }

  pushToast('Login required', 'Please login to continue', 'info');
  navigation.navigate('Login', {redirectTo});
  return false;
}

export function navigateAfterAuth(
  navigation: NativeStackNavigationProp<RootStackParamList>,
  redirectTo?: AuthRedirectTarget,
) {
  if (!redirectTo || redirectTo.screen === 'MainTabs') {
    navigation.reset({
      index: 0,
      routes: [
        {
          name: 'MainTabs',
          params: redirectTo?.params ?? {screen: 'Home'},
        },
      ],
    });
    return;
  }

  if (
    redirectTo.screen === 'MenuItemDetail' &&
    redirectTo.params.restaurantId &&
    redirectTo.params.restaurantName
  ) {
    navigation.reset({
      index: 2,
      routes: [
        {name: 'MainTabs'},
        {
          name: 'Restaurant',
          params: {
            restaurantId: redirectTo.params.restaurantId,
            restaurantName: redirectTo.params.restaurantName,
          },
        },
        {
          name: 'MenuItemDetail',
          params: {
            itemId: redirectTo.params.itemId,
            restaurantId: redirectTo.params.restaurantId,
            restaurantName: redirectTo.params.restaurantName,
          },
        },
      ],
    });
    return;
  }

  navigation.reset({
    index: 1,
    routes: [
      {name: 'MainTabs'},
      redirectTo.screen === 'Restaurant'
        ? {
            name: 'Restaurant',
            params: redirectTo.params,
          }
        : redirectTo.screen === 'MenuItemDetail'
        ? {
            name: 'MenuItemDetail',
            params: redirectTo.params,
          }
        : redirectTo.screen === 'OrderList'
        ? {
            name: 'OrderList',
          }
        : redirectTo.screen === 'OrderDetail'
        ? {
            name: 'OrderDetail',
            params: redirectTo.params,
          }
        : redirectTo.screen === 'PersonalizedPicks'
        ? {
            name: 'PersonalizedPicks',
            params: redirectTo.params,
          }
        : {
            name: redirectTo.screen,
          },
    ],
  });
}
