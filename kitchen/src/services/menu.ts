import { request } from '@services/api';
import type {
  BoardScope,
  DishStockChange,
  KitchenMenuItem,
  SizeStockChange,
} from '@/types/app';

// The kitchen's menu routes (backend/app/api/kitchen_menu.py). Scoped on the
// server by the order board's own rule; restaurant_id matters only for an
// ADMIN, and a pinned cook asking for another branch is refused.
export const fetchKitchenMenu = (token: string, scope: BoardScope) =>
  request<KitchenMenuItem[]>('/kitchen/menu', {
    token,
    query: { restaurant_id: scope.restaurantId, location_id: scope.locationId },
  });

export const updateDishStock = (
  token: string,
  menuItemId: string,
  change: DishStockChange,
  scope: BoardScope,
) =>
  request<KitchenMenuItem>(`/kitchen/menu/${menuItemId}/stock`, {
    method: 'PATCH',
    token,
    body: change,
    query: { restaurant_id: scope.restaurantId },
  });

export const updateSizeStock = (
  token: string,
  menuItemId: string,
  sizeId: string,
  change: SizeStockChange,
  scope: BoardScope,
) =>
  request<KitchenMenuItem>(`/kitchen/menu/${menuItemId}/sizes/${sizeId}/stock`, {
    method: 'PATCH',
    token,
    body: change,
    query: { restaurant_id: scope.restaurantId },
  });
