import type {GeneratedComboItem, MenuItem} from '../types/app';

interface GeneratedComboMenuItemContext {
  source: 'home-generated-combo' | 'restaurant-generated-combo' | 'cart-combo-upsell';
  restaurantId: string;
  restaurantLocationId?: string | null;
  restaurantLocationName?: string | null;
  restaurantCuisineType: string | null;
  createdAt: string;
  updatedAt: string;
}

export function buildMenuItemFromGeneratedComboItem(
  item: GeneratedComboItem,
  context: GeneratedComboMenuItemContext,
): MenuItem {
  const menuItem: MenuItem = {
    id: item.menu_item_id,
    restaurant_id: context.restaurantId,
    restaurant_location_id: item.restaurant_location_id ?? context.restaurantLocationId ?? '',
    restaurant_location_name: item.restaurant_location_name ?? context.restaurantLocationName ?? null,
    restaurant_location_city: null,
    name: item.name,
    category: item.category,
    cuisine_type: context.restaurantCuisineType,
    description: null,
    price: item.price,
    is_veg: item.is_veg,
    is_available: item.is_available,
    is_bestseller: false,
    image_url: item.image_url,
    popularity_score: 0,
    launched_at: context.createdAt,
    created_at: context.createdAt,
    updated_at: context.updatedAt,
    is_new_launch: false,
    is_new: false,
    recommendation_label: null,
    recommendation_reason: null,
    new_item_reason: null,
    is_favorite: item.is_favorite ?? false,
    has_sizes: false,
    has_customizations: false,
    sizes: [],
    customization_groups: [],
  };

  if (import.meta.env.DEV) {
    console.info('[generated-combo][veg-sync]', {
      source: context.source,
      menu_item_id: item.menu_item_id,
      item_name: item.name,
      combo_item_is_veg: item.is_veg,
      cart_item_is_veg: menuItem.is_veg,
    });
  }

  return menuItem;
}
