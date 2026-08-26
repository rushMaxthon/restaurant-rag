export type UserRole = 'ADMIN' | 'OWNER' | 'CUSTOMER';
export type NotificationAudience =
  | 'ALL_USERS'
  | 'CUSTOMERS'
  | 'OWNERS'
  | 'ADMINS'
  | 'SPECIFIC_USER';
export type NotificationType = 'GENERAL' | 'ORDER_PLACED';
export type NotificationDeepLinkType = 'order_details';
export type OrderStatus =
  // A card order that exists but has not been paid. It is not in the kitchen
  // queue and cannot be advanced until the payment provider confirms it.
  | 'PAYMENT_PENDING'
  | 'PLACED'
  | 'ACCEPTED'
  | 'PREPARING'
  | 'OUT_FOR_DELIVERY'
  | 'DELIVERED'
  | 'CANCELLED';
/** Statuses that move through the kitchen, in order. */
export const ORDER_FULFILLMENT_STATUSES: OrderStatus[] = [
  'PLACED',
  'ACCEPTED',
  'PREPARING',
  'OUT_FOR_DELIVERY',
  'DELIVERED',
];
/** Every status an order can be filtered by, fulfillment flow plus the rest. */
export const ORDER_FILTER_STATUSES: OrderStatus[] = [
  'PAYMENT_PENDING',
  ...ORDER_FULFILLMENT_STATUSES,
  'CANCELLED',
];
export type PaymentStatus =
  | 'PENDING'
  | 'PAID'
  | 'FAILED'
  | 'COD'
  | 'REFUNDED'
  | 'CANCELLED';
export type OrderFulfillmentType = 'DELIVERY' | 'PICKUP';
export type OrderScheduleType = 'ASAP' | 'SCHEDULED';
export type PaymentMethod = 'GOOGLE_PAY' | 'RAZORPAY' | 'CARD' | 'COD';
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
  /**
   * App this account belongs to. Customers always have one; ADMIN and OWNER
   * are platform accounts and leave these null.
   */
  app_client_id?: string | null;
  app_key?: string | null;
  app_mode?: AppMode | null;
  app_label?: string | null;
  restaurant_id?: string | null;
  restaurant_name?: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  restaurant_id: string | null;
  user: User;
}

export interface AuthSession {
  token: string;
  role: UserRole;
  restaurantId: string | null;
  user: User;
}

export interface DeviceTokenRegisterPayload {
  installation_id: string;
  fcm_token: string;
  platform: 'ANDROID' | 'IOS';
}

export interface NotificationHistoryItem {
  id: string;
  audience: NotificationAudience;
  notification_type: NotificationType;
  title: string;
  message: string;
  category: string | null;
  deep_link_type: NotificationDeepLinkType | null;
  order_id: string | null;
  target_user_id: string | null;
  target_user_name: string | null;
  target_user_email: string | null;
  target_user_count: number;
  sent_count: number;
  success_count: number;
  failure_count: number;
  failure_reason: string | null;
  created_by_user_id: string | null;
  created_by_name: string | null;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface SendNotificationPayload {
  audience: NotificationAudience;
  notification_type: NotificationType;
  title: string;
  message: string;
  category?: string | null;
  target_user_id?: string | null;
}

export interface SendNotificationResponse {
  history: NotificationHistoryItem;
  target_user_count: number;
  sent_count: number;
  success_count: number;
  failure_count: number;
}

export type AppMode = 'MARKETPLACE' | 'SINGLE_RESTAURANT';

export type AppClientStatus = 'ACTIVE' | 'SUSPENDED' | 'OFFBOARDED';

export interface AppClient {
  id: string;
  restaurant_id: string | null;
  app_key: string;
  display_name: string;
  app_mode: AppMode;
  status: AppClientStatus;
  ios_bundle_id: string | null;
  android_package_name: string | null;
  order_number_prefix: string;
  brand_primary_color: string | null;
  minimum_supported_version: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminCreateRestaurantPayload {
  name: string;
  owner_name: string;
  owner_email: string;
  owner_password: string;
  app_key: string;
  app_mode: AppMode;
  ios_bundle_id: string;
  android_package_name: string;
  order_number_prefix: string;
  brand_primary_color: string;
  minimum_supported_version: string;
}

export interface AdminCreateRestaurantResult extends Restaurant {
  app_client: AppClient;
}

export interface AppClientUpsertPayload {
  app_key: string;
  app_mode: AppMode;
  ios_bundle_id: string;
  android_package_name: string;
  order_number_prefix: string;
  brand_primary_color: string;
  minimum_supported_version: string;
}

export interface AdminDashboardStats {
  total_orders: number;
  total_revenue: number;
  total_restaurants: number;
  total_users: number;
}

export interface ReportsFiltersApplied {
  date_from: string | null;
  date_to: string | null;
  restaurant_id: string | null;
  cuisine_type: string | null;
  category: string | null;
  order_status: OrderStatus | null;
}

export interface ReportSummary {
  total_orders: number;
  total_revenue: number;
  total_customers: number;
  total_restaurants: number;
  average_order_value: number;
  repeat_customer_count: number;
  peak_order_hour: number | null;
  peak_order_label: string | null;
  ai_chat_sessions: number;
  favorites_count: number;
}

export interface ReportTrendPoint {
  label: string;
  value: number;
  revenue: number;
  orders: number;
}

export interface ReportStatusSummary {
  status: OrderStatus;
  count: number;
  revenue: number;
}

export interface ReportDimensionMetric {
  label: string;
  orders: number;
  revenue: number;
}

export interface ReportRestaurantScope {
  id: string;
  name: string;
  cuisine_type: string;
  city: string;
}

export interface ReportRestaurantPerformance {
  restaurant_id: string;
  restaurant_name: string;
  cuisine_type: string;
  orders: number;
  revenue: number;
  average_order_value: number;
}

export interface ReportItemPerformance {
  menu_item_id: string;
  name: string;
  restaurant_id: string;
  restaurant_name: string;
  category: string;
  quantity: number;
  revenue: number;
  favorite_count: number;
}

export interface ReportPeakHour {
  hour: number;
  label: string;
  orders: number;
}

export interface ReportChatUsage {
  total_messages: number;
  total_sessions: number;
  user_messages: number;
  assistant_messages: number;
}

export interface ReportComboPerformance {
  combo_id: string;
  combo_name: string;
  restaurant_id: string;
  restaurant_name: string;
  order_count: number;
  unique_user_count: number;
  confidence_score: number;
  suggested_combo_price: number;
  is_active: boolean;
  last_seen_at: string;
}

export interface ReportsSnapshot {
  role_scope: UserRole;
  restaurant_scope: ReportRestaurantScope | null;
  filters: ReportsFiltersApplied;
  summary: ReportSummary;
  revenue_trend: ReportTrendPoint[];
  order_status_summary: ReportStatusSummary[];
  top_restaurants: ReportRestaurantPerformance[];
  top_selling_items: ReportItemPerformance[];
  least_selling_items: ReportItemPerformance[];
  generated_combo_performance: ReportComboPerformance[];
  popular_cuisines: ReportDimensionMetric[];
  popular_categories: ReportDimensionMetric[];
  peak_order_times: ReportPeakHour[];
  chat_usage: ReportChatUsage | null;
  favorite_items: ReportItemPerformance[];
}

export interface AdminMenuItem {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant_location_name: string;
  restaurant_name: string;
  restaurant_city: string;
  name: string;
  category: string;
  cuisine_type: string | null;
  description: string | null;
  price: number | string;
  is_veg: boolean;
  is_available: boolean;
  is_bestseller: boolean;
  image_url: string | null;
  recent_valid_order_count: number;
  recent_valid_order_window_days: number;
  popularity_score: number | string;
  launched_at: string;
  created_at: string;
  updated_at: string;
  is_new_launch: boolean;
  is_new: boolean;
  has_sizes?: boolean;
  has_customizations?: boolean;
}

export interface AdminAILog {
  session_id: string;
  user_name: string;
  user_email: string;
  restaurant_name: string | null;
  query_text: string;
  reply_text: string;
  retrieved_count: number;
  filtered_count: number;
  suggestions_count: number;
  success: boolean;
  response_time_ms: number | null;
  created_at: string;
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
  minimum_order_amount: number | string;
  delivery_fee: number | string;
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
  latitude: number | string | null;
  longitude: number | string | null;
  phone_number: string | null;
  delivery_fee: number | string;
  minimum_order_amount: number | string;
  estimated_delivery_time: number;
  estimated_pickup_time: number;
  delivery_enabled: boolean;
  pickup_enabled: boolean;
  google_pay_enabled: boolean;
  razorpay_enabled: boolean;
  card_payment_enabled: boolean;
  cash_on_delivery_enabled: boolean;
  is_open: boolean;
  is_active: boolean;
  temporary_closed_reason: string | null;
  preparation_time_minutes: number | null;
  service_radius_km: number | string | null;
  future_order_enabled: boolean;
  max_future_days: number;
  slot_interval_minutes: number;
  opening_time: string | null;
  closing_time: string | null;
  delivery_available_now: boolean;
  pickup_available_now: boolean;
  delivery_unavailable_reason: string | null;
  pickup_unavailable_reason: string | null;
  enabled_payment_methods: PaymentMethod[];
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

export interface RestaurantOwnerSummary {
  id: string;
  full_name: string;
  email: string;
}

export interface RestaurantDetail extends Restaurant {
  owner: RestaurantOwnerSummary;
  locations: RestaurantLocation[];
}

export interface ManagedPersonalizedOffer {
  id: string;
  record_kind: 'TEMPLATE' | 'GENERATED';
  source: 'MANUAL_TEMPLATE' | 'AI_GENERATED';
  template_offer_id: string | null;
  template_offer_name: string | null;
  restaurant_id: string;
  restaurant_location_id: string | null;
  restaurant_location_name: string | null;
  applicable_item_id: string | null;
  applicable_item_name: string | null;
  generated_combo_id: string | null;
  generated_combo_name: string | null;
  name: string;
  offer_type: PersonalizedOfferType;
  audience_type: PersonalizedOfferAudience;
  state: PersonalizedOfferState;
  effective_state: PersonalizedOfferState;
  discount_type: PersonalizedOfferDiscountType;
  discount_value: number | string;
  max_discount_amount: number | string | null;
  minimum_order_amount: number | string;
  inactivity_days: number;
  cooldown_hours: number;
  valid_for_days: number;
  applicable_category: string | null;
  applicable_cuisine: string | null;
  cta_label: string | null;
  business_rules: Record<string, unknown>;
  notes: string | null;
  starts_at: string | null;
  expires_at: string | null;
  generation_reason: 'REPEATED_ORDER' | 'FAVORITE_RESTAURANT' | 'FIRST_ORDER' | 'INACTIVE_USER' | 'CUISINE_AFFINITY' | 'COMBO_AFFINITY' | 'BUDGET_BEHAVIOR' | 'GLOBAL_FALLBACK' | null;
  generated_title: string | null;
  generated_subtitle: string | null;
  generated_badge: string | null;
  generated_cta_label: string | null;
  manually_edited: boolean;
  edited_by: string | null;
  edited_at: string | null;
  eligible_user_count: number;
  view_count: number;
  click_count: number;
  conversion_count: number;
  editable: boolean;
  state_mutable: boolean;
  created_at: string;
  updated_at: string;
}

export interface GeneratedOfferUserMatch {
  id: string;
  generated_offer_id: string;
  user_id: string;
  user_name: string;
  user_email: string;
  matched_reason: NonNullable<ManagedPersonalizedOffer['generation_reason']>;
  score: number | string;
  rank: number;
  is_current: boolean;
  target_type: string | null;
  target_id: string | null;
  view_count: number;
  click_count: number;
  conversion_count: number;
  viewed_at: string | null;
  clicked_at: string | null;
  converted_at: string | null;
  match_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AIOfferGenerationSummary {
  users_scanned: number;
  offers_generated: number;
  offers_replaced: number;
  fallbacks_used: number;
  validation_failures: number;
  skipped_users: number;
  llm_failures: number;
  elapsed_ms: number;
  /** Segment runs only: how many patterns the analysis found. */
  segments_considered?: number;
  /** Segments already covered by a live offer, so not duplicated. */
  segments_skipped?: number;
  /** Customers whose own history made them eligible for a new offer. */
  customers_matched?: number;
}

/**
 * The response to a generation request.
 *
 * An inline run - which is what both the admin and owner triggers do - comes
 * back already finished, so it carries the same result fields as the status
 * endpoint. The type was missing them, which is why the finished result had to
 * be re-fetched to be read.
 */
export interface AdminAIOfferGenerationTriggerResponse {
  task_id: string;
  queued: boolean;
  status: string;
  message: string;
  ready: boolean;
  successful: boolean | null;
  summary: AIOfferGenerationSummary | null;
  error: string | null;
}

export interface AdminAIOfferGenerationStatusResponse {
  task_id: string;
  status: string;
  ready: boolean;
  successful: boolean | null;
  summary: AIOfferGenerationSummary | null;
  error: string | null;
}

export interface MenuItemCustomizationOption {
  id: string;
  name: string;
  extra_price: number | string;
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
  price: number | string;
  is_active: boolean;
  sort_order: number;
  customization_groups: MenuItemCustomizationGroup[];
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
  price: number | string;
  is_veg: boolean;
  is_available: boolean;
  is_bestseller: boolean;
  image_url: string | null;
  recent_valid_order_count: number;
  recent_valid_order_window_days: number;
  popularity_score: number | string;
  launched_at: string;
  created_at: string;
  updated_at: string;
  is_new_launch: boolean;
  is_new: boolean;
  recommendation_label?: string | null;
  recommendation_reason?: string | null;
  new_item_reason?: string | null;
  has_sizes: boolean;
  has_customizations: boolean;
  sizes: MenuItemSize[];
  customization_groups: MenuItemCustomizationGroup[];
}

export interface MenuItemCustomizationOptionPayload {
  name: string;
  extra_price: number;
  is_active: boolean;
  is_countable: boolean;
  sort_order: number;
}

export interface MenuItemCustomizationGroupPayload {
  title: string;
  selection_type: MenuItemCustomizationSelectionType;
  is_required: boolean;
  min_selection: number;
  max_selection: number;
  is_active: boolean;
  sort_order: number;
  options: MenuItemCustomizationOptionPayload[];
}

export interface MenuItemSizePayload {
  name: string;
  price: number;
  is_active: boolean;
  sort_order: number;
  customization_groups: MenuItemCustomizationGroupPayload[];
}

export interface MenuItemUpsertPayload {
  name: string;
  category: string;
  cuisine_type?: string | null;
  description?: string | null;
  price: number;
  is_veg: boolean;
  is_available: boolean;
  is_new_launch: boolean;
  image_url?: string | null;
  launched_at?: string | null;
  has_sizes: boolean;
  has_customizations: boolean;
  sizes: MenuItemSizePayload[];
  customization_groups: MenuItemCustomizationGroupPayload[];
  restaurant_id?: string;
  restaurant_location_id?: string | null;
}

export interface MenuItemBulkSkippedLocation {
  restaurant_location_id: string;
  restaurant_location_name: string | null;
}

export interface MenuItemBulkCreateResult {
  created: MenuItem[];
  skipped: MenuItemBulkSkippedLocation[];
}

export interface GeneratedComboItem {
  menu_item_id: string;
  restaurant_location_id: string | null;
  restaurant_location_name: string | null;
  name: string;
  category: string;
  price: number | string;
  quantity: number;
  image_url: string | null;
  is_veg: boolean;
  is_available: boolean;
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
  confidence_score: number | string;
  status: 'DRAFT' | 'LIVE' | 'ARCHIVED';
  manual_status_override?: 'DRAFT' | 'LIVE' | 'ARCHIVED' | null;
  is_customer_visible: boolean;
  remaining_unique_users_to_publish: number;
  original_total_price: number | string;
  suggested_combo_price: number | string;
  savings_amount: number | string;
  image_url: string | null;
  is_active: boolean;
  generated_from_orders: boolean;
  last_seen_at: string;
  created_at: string;
  updated_at: string;
}

export interface OrderItemSelectedOption {
  group_id?: string;
  group_title?: string;
  selection_type?: string;
  option_id?: string;
  option_name?: string;
  extra_price?: number | string;
  quantity?: number;
  is_countable?: boolean;
}

export interface OrderItem {
  id: string;
  menu_item_id: string;
  menu_item_size_id: string | null;
  item_name_snapshot: string;
  size_name_snapshot: string | null;
  quantity: number;
  base_unit_price: number | string;
  customization_total_price: number | string;
  unit_price: number | string;
  total_price: number | string;
  selected_options_snapshot: OrderItemSelectedOption[];
  created_at: string;
  updated_at: string;
}

export interface Order {
  id: string;
  customer_id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant: {
    id: string;
    name: string;
    slug: string;
    cuisine_type: string;
    city: string;
    address_line_1: string;
  };
  restaurant_location: {
    id: string;
    branch_name: string;
    city: string;
    address_line_1: string;
    delivery_fee: number | string;
    minimum_order_amount: number | string;
    estimated_delivery_time: number;
    estimated_pickup_time: number;
    delivery_enabled: boolean;
    pickup_enabled: boolean;
    enabled_payment_methods: PaymentMethod[];
    is_open: boolean;
    is_active: boolean;
  };
  customer: {
    id: string;
    full_name: string;
    email: string;
    phone_number: string | null;
  };
  status: OrderStatus;
  payment_status: PaymentStatus;
  payment_method: PaymentMethod;
  payment_provider: string;
  payment_reference: string | null;
  fulfillment_type: OrderFulfillmentType;
  schedule_type: OrderScheduleType;
  scheduled_at: string;
  subtotal: number | string;
  delivery_fee: number | string;
  tax_amount: number | string;
  discount_amount: number | string;
  total_amount: number | string;
  currency: string;
  special_instructions: string | null;
  delivery_address: string;
  placed_at: string;
  created_at: string;
  updated_at: string;
  items: OrderItem[];
}

export interface ToastMessage {
  id: number;
  title: string;
  description: string;
  tone?: 'success' | 'error' | 'info';
}

// --- AI Restaurant Manager -------------------------------------------------
// Mirrors the backend schemas in app/schemas/insights.py, owner_actions.py and
// owner_chat.py.

export interface InsightsScopeInfo {
  restaurant_id: string;
  restaurant_location_id: string | null;
  timezone: string;
}

export interface InsightsPeriodInfo {
  start_date: string;
  end_date: string;
  day_count: number;
  label: string;
}

export interface MetricDelta {
  metric: string;
  current: number;
  previous: number;
  absolute_change: number;
  percent_change: number | null;
  direction: 'up' | 'down' | 'flat';
  sufficient_data: boolean;
  note: string | null;
}

export interface InsightContribution {
  key: string;
  label: string;
  current: number;
  previous: number;
  absolute_change: number;
  percent_change: number | null;
  contribution_share: number | null;
  direction: string;
  current_orders: number;
  previous_orders: number;
  current_quantity: number;
  previous_quantity: number;
}

export interface InsightBreakdown {
  dimension: string;
  basis: string;
  parent_change: number;
  sufficient_data: boolean;
  note: string | null;
  contributions: InsightContribution[];
}

export interface AnomalyPoint {
  day: string;
  metric: string;
  value: number;
  baseline_median: number;
  robust_z: number;
  direction: string;
  severity: string;
}

export interface AnomalyReport {
  evaluated: boolean;
  baseline_days: number;
  baseline_median_orders: number;
  note: string | null;
  points: AnomalyPoint[];
}

export interface InsightsDataQuality {
  sufficient_volume: boolean;
  weekday_aligned: boolean;
  includes_partial_day: boolean;
  counted_order_statuses: string[];
  notes: string[];
}

export interface DiagnosticsSnapshot {
  scope: InsightsScopeInfo;
  current_period: InsightsPeriodInfo;
  previous_period: InsightsPeriodInfo;
  generated_at: string;
  data_quality: InsightsDataQuality;
  headline: MetricDelta[];
  breakdowns: InsightBreakdown[];
  anomalies: AnomalyReport;
}

export type OwnerInsightSeverity = 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH';
export type OwnerInsightStatus = 'NEW' | 'SEEN' | 'DISMISSED';

export interface OwnerInsight {
  id: string;
  insight_type: string;
  severity: OwnerInsightSeverity;
  status: OwnerInsightStatus;
  title: string;
  body: string;
  dimension: string | null;
  subject: string | null;
  score: number;
  /** Why it happened, when the operational history explains it. Often null. */
  root_cause: string | null;
  period_start: string;
  period_end: string;
  facts: Record<string, unknown>;
  created_at: string;
  acknowledged_at: string | null;
  /** Computed for the period on screen; no stored row behind it yet. */
  is_live?: boolean;
}

export interface OwnerBriefing {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string | null;
  period_start: string;
  period_end: string;
  previous_period_start: string;
  previous_period_end: string;
  headline: string;
  narrative: string;
  narration_source: 'TEMPLATE' | 'LLM';
  insight_count: number;
  generated_at: string;
  insights: OwnerInsight[];
  /** Computed for the period on screen rather than read from the nightly run. */
  is_live: boolean;
  /** The stored briefing no longer reaches the last complete day. */
  is_stale: boolean;
  stale_reason: string | null;
}

export type OwnerActionStatus =
  | 'PROPOSED'
  | 'APPROVED'
  | 'EXECUTED'
  | 'REJECTED'
  | 'FAILED'
  | 'EXPIRED';

export interface OwnerActionProposal {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string | null;
  insight_id: string | null;
  briefing_id: string | null;
  action_type: string;
  status: OwnerActionStatus;
  title: string;
  rationale: string;
  is_executable: boolean;
  priority: number;
  expected_impact_amount: number | null;
  expected_impact_basis: string | null;
  action_payload: Record<string, unknown>;
  source_facts: Record<string, unknown>;
  generated_at: string;
  expires_at: string | null;
  decided_at: string | null;
  executed_at: string | null;
  executed_offer_id: string | null;
  failure_reason: string | null;
  outcome: ActionOutcome | null;
}

export type ActionOutcomeVerdict =
  | 'NO_UPTAKE'
  | 'BELOW_ESTIMATE'
  | 'MET_ESTIMATE'
  | 'ABOVE_ESTIMATE'
  | 'NOT_MEASURABLE';

/**
 * What was observed after an approved action ran. Orders that *used* the offer
 * — not orders it can be shown to have caused, since there is no holdout group.
 */
export interface ActionOutcome {
  id: string;
  proposal_id: string;
  offer_id: string | null;
  verdict: ActionOutcomeVerdict;
  window_start: string;
  window_end: string;
  window_days: number;
  attributed_orders: number;
  attributed_customers: number;
  attributed_revenue: number;
  discount_cost: number;
  net_revenue: number;
  estimated_impact: number | null;
  summary: string;
  measured_at: string;
}

export interface OwnerActionApproval {
  proposal: OwnerActionProposal;
  offer_id: string | null;
  already_executed: boolean;
  detail: string;
}

export interface OfferPerformanceRow {
  offer_id: string;
  offer_name: string;
  offer_kind: 'TEMPLATE' | 'GENERATED';
  orders: number;
  customers: number;
  gross_revenue: number;
  discount_cost: number;
  net_revenue: number;
  average_order_value: number;
  return_per_unit_discount: number | null;
  views: number;
  clicks: number;
  conversions: number;
  click_through_rate: number | null;
  conversion_rate: number | null;
}

export interface OfferPerformanceSnapshot {
  scope: InsightsScopeInfo;
  period: InsightsPeriodInfo;
  total_gross_revenue: number;
  total_discount_cost: number;
  total_orders: number;
  offers: OfferPerformanceRow[];
}

/**
 * One actionable offer or combo the assistant suggested.
 *
 * Built server-side from the same rows the answer was written from, so a card
 * can never state a discount or a price the underlying record does not carry.
 * `action` is the single thing the owner can do with it, already resolved
 * against the target's real state - the client never has to work out whether a
 * suggestion needs creating or merely activating.
 */
export interface SuggestionCard {
  version: number;
  kind: 'offer' | 'combo';
  /** The proposal (for `create`) or the offer/combo itself (for `activate`). */
  id: string;
  /** The live offer/combo once one exists, for the View action. */
  target_id: string | null;
  title: string;
  summary: string | null;
  status: string;
  state: 'creatable' | 'activatable' | 'active';
  action: 'create' | 'activate' | null;
  action_label: string;
  details: Array<{ label: string; value: string }>;
  discount: { type: string; value: number } | null;
  minimum_order_amount: number | null;
  valid_for_days: number | null;
  pricing: { original: number | null; offered: number | null; saving: number | null } | null;
  reason: string | null;
  expected_impact: number | null;
  expected_impact_basis: string | null;
  evidence: Array<{ label: string; value: string }>;
}

export interface OwnerChatAnswer {
  session_id: string;
  answer: string;
  skill: string;
  answer_source: 'TEMPLATE' | 'LLM';
  routed_by: string;
  fallback_reason: string | null;
  facts: Record<string, unknown>;
  suggestions: SuggestionCard[];
}

export interface SuggestionOfferActivation {
  offer_id: string;
  name: string;
  state: string;
  already_active: boolean;
  detail: string;
}

export interface OwnerChatHistoryItem {
  id: string;
  session_id: string;
  role: 'USER' | 'ASSISTANT';
  message: string;
  skill: string | null;
  answer_source: string | null;
  created_at: string;
  /** Replayed with the message, so a restored thread keeps its cards. */
  suggestions: SuggestionCard[];
}

export interface OwnerChatClearResult {
  deleted_count: number;
  cleared_session_id: string | null;
}
