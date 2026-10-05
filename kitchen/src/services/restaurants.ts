import { request } from '@services/api';
import type { RestaurantInfo } from '@/types/app';

// The brand and its branches, for the header and the branch picker. Public,
// and read off the restaurant itself: one deployment serves every tenant, so
// the board must be able to say whose kitchen it is showing.
export const fetchRestaurant = async (restaurantId: string): Promise<RestaurantInfo> => {
  const info = await request<RestaurantInfo>(`/restaurants/${restaurantId}`);
  return { ...info, locations: info.locations ?? [] };
};
