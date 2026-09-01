import { createContext } from 'react';
import type { AppConfig } from '../types/app';

export interface AppConfigValue {
  config: AppConfig | null;
  /** The restaurant this build is scoped to, or null in marketplace mode. */
  restaurantId: string | null;
  isSingleRestaurant: boolean;
  displayName: string;
  brandColor: string | null;
  /** False only until the first fetch settles; a cached config is used meanwhile. */
  ready: boolean;
}

export const AppConfigContext = createContext<AppConfigValue>({
  config: null,
  restaurantId: null,
  isSingleRestaurant: false,
  displayName: 'QuickBite',
  brandColor: null,
  ready: false,
});

