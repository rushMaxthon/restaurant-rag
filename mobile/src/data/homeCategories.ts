export interface HomeCategory {
  id: string;
  label: string;
  icon: string;
  query: string;
}

export const homeCategories: HomeCategory[] = [
  {id: 'pizza', label: 'Pizza', icon: 'pizza-outline', query: 'pizza'},
  {id: 'burgers', label: 'Burgers', icon: 'fast-food-outline', query: 'burger'},
  {id: 'chinese', label: 'Chinese', icon: 'restaurant-outline', query: 'chinese'},
  {id: 'healthy', label: 'Healthy', icon: 'leaf-outline', query: 'healthy'},
  {id: 'desserts', label: 'Desserts', icon: 'ice-cream-outline', query: 'dessert'},
  {id: 'biryani', label: 'Biryani', icon: 'flame-outline', query: 'biryani'},
  {id: 'beverages', label: 'Drinks', icon: 'wine-outline', query: 'beverage'},
  {id: 'quick', label: 'Quick', icon: 'flash-outline', query: 'quick'},
];
