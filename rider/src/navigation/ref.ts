import { createNavigationContainerRef } from '@react-navigation/native';

import type { RootStackParamList } from './types';

/** For code outside any screen - a notification tap - that must still move the rider somewhere. */
export const navigationRef = createNavigationContainerRef<RootStackParamList>();
