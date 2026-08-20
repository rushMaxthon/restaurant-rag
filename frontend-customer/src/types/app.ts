export type DecimalValue = number | string;

export type UserRole = 'ADMIN' | 'OWNER' | 'CUSTOMER';
export type DietPreference = 'VEG' | 'NON_VEG';
export type SpiceLevel = 'LOW' | 'MEDIUM' | 'HIGH';
export type BudgetTier = 'LOW' | 'MID' | 'HIGH';
export type OrderStatus = 'PLACED' | 'ACCEPTED' | 'PREPARING' | 'OUT_FOR_DELIVERY' | 'DELIVERED';
export type PaymentStatus = 'PENDING' | 'PAID' | 'FAILED' | 'REFUNDED';
export type ChatRole = 'USER' | 'ASSISTANT';
export type OrderFulfillmentType = 'DELIVERY' | 'PICKUP';
export type LocationDayOfWeek =
  | 'MONDAY'
  | 'TUESDAY'
  | 'WEDNESDAY'
  | 'THURSDAY'
  | 'FRIDAY'
  | 'SATURDAY'
  | 'SUNDAY';
export type PersonalizedOfferType =
  | 'WELCOME_FIRST_ORDER'
  | 'FAVORITE_ITEM'
  | 'FAVORITE_RESTAURANT'
  | 'PREFERENCE_MATCH'
  | 'ORDER_HISTORY_MATCH'
  | 'NEW_ITEM_MATCH'
  | 'TASTE_MATCH'
  | 'CUISINE_AFFINITY'
  | 'BUDGET_BEHAVIOR'
  | 'COMBO_AFFINITY'
  | 'CUSTOM';
export type PersonalizedOfferAudience = 'ACTIVE_USERS' | 'INACTIVE_USERS' | 'ALL_CUSTOMERS';
export type PersonalizedOfferState = 'DRAFT' | 'ACTIVE' | 'PAUSED' | 'EXPIRED' | 'DISABLED';
export type PersonalizedOfferDiscountType = 'NONE' | 'PERCENTAGE' | 'FLAT' | 'FREE_DELIVERY';
export type MenuItemCustomizationSelectionType = 'SINGLE' | 'MULTI';

export interface User {
  id: string;
  full_name: string;
  email: string;
  phone_number: string | null;
  default_address: string | null;
  role: UserRole;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  restaurant_id: string | null;
  user: User;
}

export interface UserPreferences {
  cuisines: string[];
  diet: DietPreference | null;
  spice_level: SpiceLevel | null;
  budget: BudgetTier | null;
  favorite_items: string[];
  updated_at?: string | null;
}

export interface ProfileStats {
  total_orders: number;
  delivered_orders: number;
  saved_places: number;
  favorites_count: number;
}

export interface ProfileSummary {
  user: User;
  stats: ProfileStats;
  preferences: UserPreferences | null;
  recent_orders: Order[];
}

export interface ProfileUpdatePayload {
  full_name: string;
  phone_number: string | null;
  default_address: string | null;
}

export interface Restaurant {
  id: string;
  owner_id: string;
  name: string;
  slug: string;
  description: string | null;
  cuisine_type: string;
  address_line_1: string;
  address_line_2: string | null;
  city: string;
  state: string;
  country: string;
  postal_code: string;
  phone_number: string | null;
  minimum_order_amount: DecimalValue;
  delivery_fee: DecimalValue;
  logo_image_url: string | null;
  cover_image_url: string | null;
  is_approved: boolean;
  is_open: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  locations?: RestaurantLocation[];
}

export interface RestaurantLocation {
  id: string;
  restaurant_id: string;
  branch_name: string;
  address_line_1: string;
  address_line_2: string | null;
  city: string;
  state: string;
  postal_code: string;
  latitude: DecimalValue | null;
  longitude: DecimalValue | null;
  phone_number: string | null;
  delivery_fee: DecimalValue;
  minimum_order_amount: DecimalValue;
  estimated_delivery_time: number;
  estimated_pickup_time: number;
  delivery_enabled: boolean;
  pickup_enabled: boolean;
  is_open: boolean;
  is_active: boolean;
  temporary_closed_reason: string | null;
  preparation_time_minutes: number | null;
  service_radius_km: DecimalValue | null;
  opening_time: string | null;
  closing_time: string | null;
  delivery_available_now: boolean;
  pickup_available_now: boolean;
  delivery_unavailable_reason: string | null;
  pickup_unavailable_reason: string | null;
  fulfillment_slots: LocationFulfillmentSlot[];
  created_at: string;
  updated_at: string;
}

export interface LocationFulfillmentSlot {
  id: string;
  location_id: string;
  day_of_week: LocationDayOfWeek;
  fulfillment_type: OrderFulfillmentType;
  start_time: string;
  end_time: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface MenuItem {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant_location_name: string | null;
  restaurant_location_city: string | null;
  name: string;
  category: string;
  cuisine_type: string | null;
  description: string | null;
  price: DecimalValue;
  is_veg: boolean;
  is_available: boolean;
  is_bestseller: boolean;
  image_url: string | null;
  popularity_score: DecimalValue;
  launched_at: string;
  created_at: string;
  updated_at: string;
  is_new_launch: boolean;
  is_new: boolean;
  recommendation_label?: string | null;
  recommendation_reason?: string | null;
  new_item_reason?: string | null;
  is_favorite: boolean;
  has_sizes: boolean;
  has_customizations: boolean;
  sizes: MenuItemSize[];
  customization_groups: MenuItemCustomizationGroup[];
}

export interface MenuItemCustomizationOption {
  id: string;
  name: string;
  extra_price: DecimalValue;
  is_active: boolean;
  is_countable: boolean;
  sort_order: number;
}

export interface MenuItemCustomizationGroup {
  id: string;
  menu_item_size_id: string | null;
  title: string;
  selection_type: MenuItemCustomizationSelectionType;
  is_required: boolean;
  min_selection: number;
  max_selection: number;
  is_active: boolean;
  sort_order: number;
  options: MenuItemCustomizationOption[];
}

export interface MenuItemSize {
  id: string;
  name: string;
  price: DecimalValue;
  is_active: boolean;
  sort_order: number;
  customization_groups: MenuItemCustomizationGroup[];
}

export interface FavoriteItem extends MenuItem {
  restaurant_location_id: string;
  restaurant_location_name: string;
  restaurant_name: string;
  restaurant_slug: string;
  restaurant_is_active: boolean;
  restaurant_is_approved: boolean;
  restaurant_is_open: boolean;
  is_orderable: boolean;
  favorited_at: string;
}

export interface RecommendationRestaurantSummary {
  id: string;
  name: string;
  slug: string;
  cuisine_type: string;
  city: string;
  is_open: boolean;
}

export interface RecommendationScoreBreakdown {
  cuisine_match: number;
  order_history: number;
  popularity: number;
  budget_fit: number;
  novelty: number;
}

export interface RecommendationItem extends MenuItem {
  score: number;
  restaurant: RecommendationRestaurantSummary;
  restaurant_location: RecommendationLocationSummary;
  score_breakdown: RecommendationScoreBreakdown;
  display_price?: DecimalValue | null;
  price_label?: string | null;
  available_locations_count?: number;
  preferred_menu_item_id?: string | null;
  preferred_location_id?: string | null;
  preferred_location_name?: string | null;
  requires_location_selection?: boolean;
  location_variants?: RecommendationLocationVariant[];
}

export interface RecommendationLocationSummary {
  id: string;
  branch_name: string;
  city: string;
  latitude?: DecimalValue | null;
  longitude?: DecimalValue | null;
  is_open: boolean;
  is_active: boolean;
  delivery_fee: DecimalValue;
  minimum_order_amount: DecimalValue;
  estimated_delivery_time: number;
}

export interface RecommendationLocationVariant {
  menu_item_id: string;
  restaurant_location_id: string;
  branch_name: string;
  city: string;
  price: DecimalValue;
  is_open: boolean;
  is_active: boolean;
}

export interface GeneratedComboItem {
  menu_item_id: string;
  restaurant_location_id: string | null;
  restaurant_location_name: string | null;
  name: string;
  category: string;
  price: DecimalValue;
  quantity: number;
  image_url: string | null;
  is_veg: boolean;
  is_available: boolean;
  is_favorite: boolean;
}

export interface GeneratedCombo {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant_name: string;
  restaurant_location_name: string;
  combo_name: string;
  description: string | null;
  items: GeneratedComboItem[];
  order_count: number;
  unique_user_count: number;
  confidence_score: DecimalValue;
  original_total_price: DecimalValue;
  suggested_combo_price: DecimalValue;
  savings_amount: DecimalValue;
  image_url: string | null;
  is_active: boolean;
  generated_from_orders: boolean;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface ComboUpsellSuggestion {
  combo_id: string;
  combo_name: string;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant_name: string;
  restaurant_location_name: string;
  confidence_score: DecimalValue;
  suggested_combo_price: DecimalValue;
  missing_items: GeneratedComboItem[];
  message: string;
}

export interface ChatSuggestionItem {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant_name: string;
  restaurant_location_name: string;
  name: string;
  category: string;
  cuisine_type: string | null;
  description: string | null;
  price: DecimalValue;
  is_veg: boolean;
  is_available: boolean;
  is_bestseller: boolean;
  image_url: string | null;
  launched_at: string;
  is_new_launch: boolean;
  is_new: boolean;
  recommendation_label?: string | null;
  recommendation_reason?: string | null;
  new_item_reason?: string | null;
  is_favorite: boolean;
  similarity_score: number;
}

export interface ChatMessageRequest {
  message: string;
  restaurant_id?: string | null;
  restaurant_location_id?: string | null;
  session_id?: string | null;
}

export interface ChatMessageResponse {
  reply: string;
  session_id: string;
  suggestions: ChatSuggestionItem[];
  combo_suggestions: GeneratedCombo[];
  offer_suggestions: PersonalizedOfferCard[];
}

export interface ChatHistoryItem {
  id: string;
  session_id: string;
  restaurant_id: string | null;
  restaurant_location_id: string | null;
  role: ChatRole;
  message: string;
  context_payload: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface OrderRestaurantSummary {
  id: string;
  name: string;
  slug: string;
  cuisine_type: string;
  city: string;
}

export interface OrderRestaurantLocationSummary {
  id: string;
  branch_name: string;
  city: string;
  address_line_1: string;
  delivery_fee: DecimalValue;
  minimum_order_amount: DecimalValue;
  estimated_delivery_time: number;
  estimated_pickup_time: number;
  delivery_enabled: boolean;
  pickup_enabled: boolean;
  is_open: boolean;
  is_active: boolean;
}

export interface OrderCustomerSummary {
  id: string;
  full_name: string;
  email: string;
  phone_number: string | null;
}

export interface OrderItem {
  id: string;
  menu_item_id: string;
  menu_item_size_id: string | null;
  item_name_snapshot: string;
  size_name_snapshot: string | null;
  quantity: number;
  base_unit_price: DecimalValue;
  customization_total_price: DecimalValue;
  unit_price: DecimalValue;
  total_price: DecimalValue;
  selected_options_snapshot: OrderItemSelectedOptionSnapshot[];
  created_at: string;
  updated_at: string;
}

export interface OrderItemSelectedOptionSnapshot {
  group_id: string;
  group_title: string;
  selection_type: MenuItemCustomizationSelectionType;
  option_id: string;
  option_name: string;
  extra_price: DecimalValue;
  quantity: number;
  is_countable: boolean;
}

export interface Order {
  id: string;
  customer_id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant: OrderRestaurantSummary;
  restaurant_location: OrderRestaurantLocationSummary;
  customer: OrderCustomerSummary;
  status: OrderStatus;
  payment_status: PaymentStatus;
  payment_provider: string;
  payment_reference: string | null;
  fulfillment_type: OrderFulfillmentType;
  subtotal: DecimalValue;
  delivery_fee: DecimalValue;
  tax_amount: DecimalValue;
  discount_amount: DecimalValue;
  total_amount: DecimalValue;
  currency: string;
  special_instructions: string | null;
  delivery_address: string;
  placed_at: string;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
}

export interface PersonalizedOfferCard {
  id: string;
  generated_offer_id: string | null;
  generated_offer_user_match_id: string | null;
  offer_id: string;
  offer_name: string;
  offer_type: PersonalizedOfferType;
  audience_type: PersonalizedOfferAudience;
  badge: string;
  title: string;
  subtitle: string;
  cta_label: string;
  target_type: string;
  restaurant_id: string;
  restaurant_name: string;
  restaurant_slug: string;
  restaurant_location_id: string | null;
  restaurant_location_name: string | null;
  offer_restaurant_location_id: string | null;
  menu_item_id: string | null;
  menu_item_name: string | null;
  generated_combo_id: string | null;
  generated_combo_name: string | null;
  cuisine_type: string | null;
  discount_type: PersonalizedOfferDiscountType;
  discount_value: DecimalValue;
  discount_label: string | null;
  max_discount_amount: DecimalValue | null;
  minimum_order_amount: DecimalValue;
  terms_label: string | null;
  valid_for_days: number;
  expires_at: string | null;
  created_at: string;
}

export interface AppliedPersonalizedOffer {
  generatedOfferId: string | null;
  generatedOfferUserMatchId: string | null;
  offerId: string;
  offerName: string;
  offerType: PersonalizedOfferType;
  audienceType: PersonalizedOfferAudience;
  targetType: string;
  restaurantId: string;
  restaurantName: string;
  restaurantLocationId: string | null;
  restaurantLocationName: string | null;
  offerRestaurantLocationId: string | null;
  menuItemId: string | null;
  generatedComboId: string | null;
  cuisineType: string | null;
  title: string;
  ctaLabel: string;
  discountType: PersonalizedOfferDiscountType;
  discountValue: DecimalValue;
  discountLabel: string | null;
  maxDiscountAmount: DecimalValue | null;
  minimumOrderAmount: DecimalValue;
  termsLabel: string | null;
  expiresAt: string | null;
}

export interface PersonalizedOfferPreview {
  offer_id: string;
  eligible: boolean;
  offer_name: string | null;
  offer_title: string | null;
  offer_restaurant_location_id: string | null;
  discount_type: PersonalizedOfferDiscountType | null;
  discount_value: DecimalValue;
  discount_amount: DecimalValue;
  discount_label: string | null;
  max_discount_amount: DecimalValue | null;
  minimum_order_amount: DecimalValue;
  subtotal: DecimalValue;
  amount_to_unlock: DecimalValue;
  message: string | null;
}

export interface PersonalizedOfferItemAvailability {
  menu_item_id: string;
  has_offer: boolean;
  offer_count: number;
}

export interface PendingOfferPrompt {
  menuItem: MenuItem;
  restaurantId: string;
  restaurantName: string;
  restaurantLocationId: string;
  restaurantLocationName: string;
  quantity: number;
  silent: boolean;
  offers: PersonalizedOfferCard[];
  selectedSize?: CartSelectedSize | null;
  selectedOptions?: CartSelectedOption[];
  unitPrice?: DecimalValue;
}

export interface CartSelectedOption {
  groupId: string;
  groupTitle: string;
  selectionType: MenuItemCustomizationSelectionType;
  optionId: string;
  optionName: string;
  extraPrice: DecimalValue;
  quantity: number;
  isCountable: boolean;
}

export interface CartSelectedSize {
  id: string;
  name: string;
  price: DecimalValue;
}

export interface CartItem {
  id: string;
  menuItem: MenuItem;
  quantity: number;
  selectedSize: CartSelectedSize | null;
  selectedOptions: CartSelectedOption[];
  unitPrice: DecimalValue;
}

export type CartFulfillmentType = 'DELIVERY' | 'PICKUP';

export interface CartState {
  restaurantId: string | null;
  restaurantName: string | null;
  restaurantLocationId: string | null;
  restaurantLocationName: string | null;
  fulfillmentType: CartFulfillmentType;
  items: CartItem[];
}

export interface CartReplacementPrompt {
  menuItem: MenuItem;
  restaurantId: string;
  restaurantName: string;
  restaurantLocationId: string;
  restaurantLocationName: string;
  selectedPersonalizedOffer: AppliedPersonalizedOffer | null;
  quantity: number;
  selectedSize?: CartSelectedSize | null;
  selectedOptions?: CartSelectedOption[];
  unitPrice?: DecimalValue;
}

export interface ToastMessage {
  id: number;
  title: string;
  description: string;
  tone?: 'success' | 'error' | 'info';
}
