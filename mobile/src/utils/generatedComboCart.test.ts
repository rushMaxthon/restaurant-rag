import {buildMenuItemFromGeneratedComboItem} from './generatedComboCart';

describe('buildMenuItemFromGeneratedComboItem', () => {
  it('preserves the source menu item veg flag for combo items', () => {
    const menuItem = buildMenuItemFromGeneratedComboItem(
      {
        menu_item_id: 'iced-lemon-soda-id',
        restaurant_location_id: 'branch-id',
        restaurant_location_name: 'Main Branch',
        name: 'Iced Lemon Soda',
        category: 'Beverages',
        price: 99,
        quantity: 1,
        image_url: 'https://example.com/iced-lemon-soda.png',
        is_veg: true,
        is_available: true,
        is_favorite: false,
      },
      {
        source: 'home-generated-combo',
        restaurantId: 'restaurant-id',
        restaurantCuisineType: 'Italian',
        createdAt: '2026-05-14T00:00:00.000Z',
        updatedAt: '2026-05-14T00:00:00.000Z',
      },
    );

    expect(menuItem.id).toBe('iced-lemon-soda-id');
    expect(menuItem.name).toBe('Iced Lemon Soda');
    expect(menuItem.is_veg).toBe(true);
  });
});
