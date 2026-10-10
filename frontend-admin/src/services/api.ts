import type {
  PairingCode as PairingCodeDto,
  PrintAgent as PrintAgentDto,
  PrintJob as PrintJobDto,
  Printer as PrinterDto,
} from '../types/printing';
import type {
  BrandFaq,
  BrandHighlight,
  BrandSection,
  RestaurantBrand,
  RestaurantStorefront,
  StorefrontCopyKey,
  BranchLocationLookup,
  OrderDelivery,
  LiveOrdersBoard,
  AdminAILog,
  AdminPreferenceOption,
  AdminPreferenceQuestion,
  PreferenceOptionDraft,
  PreferenceQuestionDraft,
  AdminAIOfferGenerationStatusResponse,
  AdminAIOfferGenerationTriggerResponse,
  AdminCreateRestaurantPayload,
  AdminCreateRestaurantResult,
  AdminDashboardStats,
  AppClient,
  AppClientUpsertPayload,
  PaymentGateway,
  PaymentGatewayPayload,
  CommissionReport,
  AdminUserStats,
  UserRole,
  DeliveryPricing,
  TrafficOverview,
  TrafficSummary,
  DeliveryPricingInput,
  PayoutAccount,
  PayoutAccountInput,
  PayoutList,
  PlatformWatch,
  RestaurantCapability,
  RestaurantPaymentSettings,
  TenantStatusPayload,
  TenantSummary,
  ReportsSnapshot,
  GeneratedCombo,
  AdminMenuItem,
  AuthResponse,
  GeneratedOfferUserMatch,
  ManagedPersonalizedOffer,
  MenuItem,
  MenuItemBulkCreateResult,
  MenuItemUpsertPayload,
  Order,
  OrderStatus,
  KitchenStaff,
  KitchenStaffCreatePayload,
  KitchenStaffUpdatePayload,
  RestaurantDetail,
  LocationFulfillmentSlot,
  RestaurantLocation,
  Restaurant,
  SendNotificationPayload,
  SendNotificationResponse,
  NotificationHistoryItem,
  User,
  DiagnosticsSnapshot,
  OfferPerformanceSnapshot,
  OwnerActionApproval,
  OwnerActionProposal,
  OwnerBriefing,
  OwnerChatAnswer,
  OwnerChatClearResult,
  RestaurantTheme,
  SuggestionOfferActivation,
  OwnerChatHistoryItem,
  OwnerInsight,
  OwnerInsightStatus,
  ActionOutcome,
  FleetConfig,
  FleetDeliveryView,
  FleetSettings,
  Rider,
  RiderCreateInput,
  AdminReferralRow,
  ReferralSettings,
  ReferralStatus,
  RiderPay,
  RiderPayoutRecord,
  RiderTripToPrice,
  RiderUnpaid,
  ApplicationStatus,
  ItemKind,
  RiderApplicationDetail,
  RiderApplicationSummary,
  RiderUpdateInput,
  WaitingFleetOrder,
  MapBranch,
} from '../types/app';

// Imported for the fetch calls below AND re-exported, because
// services/aiManagerStream.ts already imports API_BASE_URL from this module:
// the public surface stays exactly as it was, while the value itself now comes
// from the single config module.
import { API_BASE_URL } from '../config/api';

export { API_BASE_URL };

export const AUTH_INVALID_EVENT = 'restaurant-rag-admin-auth-invalid';

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  token?: string | null;
  body?: unknown;
};

/**
 * Turns FastAPI's 422 body into something a person can act on.
 *
 * A validation failure arrives as `detail: [{loc, msg, ...}]` — a LIST, not a
 * string. Every caller here reads `detail` expecting a string, so until now
 * every 422 in the admin surfaced as the generic "Something went wrong": the
 * one error class that says exactly which field is wrong was the one class
 * that told the user nothing. It also made these bugs undiagnosable from a
 * screenshot.
 *
 * `loc` is ["body", "content", "title"] or ["query", "restaurant_id"]; the
 * first element is the request part and is noise to the reader, so the field
 * path is everything after it.
 *
 * Returns null when this is not a validation body, so the existing fallbacks
 * still run.
 */
function formatValidationDetail(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) {
    return null;
  }

  const messages = detail
    .map((entry) => {
      if (entry === null || typeof entry !== 'object') {
        return null;
      }
      const { loc, msg } = entry as { loc?: unknown; msg?: unknown };
      if (typeof msg !== 'string') {
        return null;
      }
      const field = Array.isArray(loc)
        ? loc.slice(1).filter((part) => typeof part === 'string').join('.')
        : '';
      return field ? `${field}: ${msg}` : msg;
    })
    .filter((message): message is string => message !== null);

  if (messages.length === 0) {
    return null;
  }
  // More than two and the toast becomes a wall; the rest are in `detail` on
  // the ApiError for anyone reading the console.
  const shown = messages.slice(0, 2).join('; ');
  return messages.length > 2 ? `${shown} (+${messages.length - 2} more)` : shown;
}

/**
 * The one fetch wrapper. Exported because the Marketing Hub's client needs the
 * same 401 -> sign-out event and the same `detail` unwrapping; duplicating
 * either would mean an expired session behaving differently on one screen.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers();
  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }
  if (options.token) {
    headers.set('Authorization', `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    // Expired/invalid sessions redirect to login instead of dead-ending in
    // repeated error toasts. Login failures (/auth/*) keep their own message.
    if (response.status === 401 && !path.startsWith('/auth/')) {
      window.dispatchEvent(new CustomEvent(AUTH_INVALID_EVENT));
      throw new ApiError('Your session has expired. Please sign in again.', 401);
    }
    const rawDetail: unknown = payload.detail;
    const detailMessage =
      typeof rawDetail === 'string'
        ? rawDetail
        : formatValidationDetail(rawDetail) ??
          (rawDetail !== null &&
          typeof rawDetail === 'object' &&
          typeof (rawDetail as { message?: unknown }).message === 'string'
            ? (rawDetail as { message: string }).message
            : typeof payload.message === 'string'
              ? payload.message
              : 'Something went wrong');
    throw new ApiError(detailMessage, response.status, rawDetail);
  }

  return payload as T;
}

function scopeQuery(restaurantId?: string | null): string {
  return restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : '';
}

export const api = {
  login(input: { email: string; password: string }): Promise<AuthResponse> {
    return request<AuthResponse>('/auth/login', { method: 'POST', body: input });
  },
  /** System health, what needs attention, and today per restaurant. ADMIN only. */
  getPlatformWatch(token: string): Promise<PlatformWatch> {
    return request<PlatformWatch>('/admin/platform-watch', { token });
  },
  /** What the platform earned per restaurant over the last `days`. ADMIN only. */
  getPayouts(token: string, query: { restaurant_id?: string; date_from?: string; date_to?: string }): Promise<PayoutList> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value) params.set(key, value);
    }
    return request<PayoutList>(`/payouts?${params.toString()}`, { token });
  },
  retryPayout(token: string, payoutId: string): Promise<{ status: string; last_error: string | null }> {
    return request(`/payouts/${payoutId}/retry`, { method: "POST", token });
  },
  /** An owner passes no restaurant: the server pins them to their own. */
  getPayoutAccount(token: string, restaurantId?: string): Promise<PayoutAccount | null> {
    const query = restaurantId ? `?restaurant_id=${restaurantId}` : "";
    return request<PayoutAccount | null>(`/payouts/account${query}`, { token });
  },
  savePayoutAccount(token: string, restaurantId: string, body: PayoutAccountInput): Promise<PayoutAccount> {
    return request<PayoutAccount>(`/payouts/account?restaurant_id=${restaurantId}`, { method: "PUT", token, body });
  },
  submitPayoutAccount(token: string, restaurantId: string): Promise<PayoutAccount> {
    return request<PayoutAccount>(`/payouts/account/submit?restaurant_id=${restaurantId}`, { method: "POST", token });
  },
  refreshPayoutAccount(token: string, restaurantId: string): Promise<PayoutAccount> {
    return request<PayoutAccount>(`/payouts/account/refresh?restaurant_id=${restaurantId}`, { method: "POST", token });
  },
  getCommissionReport(token: string, days: number): Promise<CommissionReport> {
    return request<CommissionReport>(`/admin/commission?days=${days}`, { token });
  },
  getTrafficSummary(token: string, restaurantId?: string | null): Promise<TrafficSummary> {
    const query = restaurantId ? `?restaurant_id=${restaurantId}` : '';
    return request<TrafficSummary>(`/traffic/summary${query}`, { token });
  },
  getTrafficOverview(token: string): Promise<TrafficOverview> {
    return request<TrafficOverview>('/traffic/overview', { token });
  },
  getDeliveryPricing(token: string): Promise<DeliveryPricing> {
    return request<DeliveryPricing>('/admin/delivery-pricing', { token });
  },
  saveDeliveryPricing(token: string, body: DeliveryPricingInput): Promise<DeliveryPricing> {
    return request<DeliveryPricing>('/admin/delivery-pricing', { method: "PUT", token, body });
  },
  // --- own delivery fleet (admin only) ---
  listRiders(token: string): Promise<Rider[]> {
    return request<Rider[]>('/admin/riders', { token });
  },
  /** Riders on shift (online or on a trip) with their last position, for the live map. */
  listLiveRiders(token: string): Promise<Rider[]> {
    return request<Rider[]>('/admin/riders/live', { token });
  },
  /** Fleet orders nobody is carrying yet; assign one with `reassignFleetDelivery`. */
  listWaitingFleetOrders(token: string): Promise<WaitingFleetOrder[]> {
    return request<WaitingFleetOrder[]>('/admin/riders/waiting', { token });
  },
  /** Restaurant branches with a map pin, and whether our riders serve them. */
  listMapBranches(token: string): Promise<MapBranch[]> {
    return request<MapBranch[]>('/admin/riders/branches', { token });
  },
  createRider(token: string, body: RiderCreateInput): Promise<Rider> {
    return request<Rider>('/admin/riders', { method: 'POST', token, body });
  },
  updateRider(token: string, userId: string, body: RiderUpdateInput): Promise<Rider> {
    return request<Rider>(`/admin/riders/${userId}`, { method: 'PATCH', token, body });
  },
  getFleetSettings(token: string): Promise<FleetSettings> {
    return request<FleetSettings>('/admin/riders/settings', { token });
  },
  saveRiderPay(token: string, body: RiderPay): Promise<FleetSettings> {
    return request<FleetSettings>('/admin/riders/settings/pay', { method: 'PUT', token, body });
  },
  listTripsToPrice(token: string): Promise<RiderTripToPrice[]> {
    return request<RiderTripToPrice[]>('/admin/riders/trips/to-price', { token });
  },
  priceTrip(token: string, tripId: string, amount: string): Promise<{ trip_id: string; earning_amount: string }> {
    return request(`/admin/riders/trips/${tripId}/pay`, { method: 'PUT', token, body: { amount } });
  },
  getReferralSettings(token: string): Promise<ReferralSettings> {
    return request<ReferralSettings>('/admin/riders/settings/referral', { token });
  },
  saveReferralSettings(token: string, body: ReferralSettings): Promise<ReferralSettings> {
    return request<ReferralSettings>('/admin/riders/settings/referral', { method: 'PUT', token, body });
  },
  listReferrals(token: string, status?: ReferralStatus): Promise<AdminReferralRow[]> {
    const query = status ? `?status=${status}` : '';
    return request<AdminReferralRow[]>(`/admin/riders/referrals${query}`, { token });
  },
  cancelReferral(token: string, referredUserId: string, reason: string): Promise<AdminReferralRow> {
    return request<AdminReferralRow>(`/admin/riders/referrals/${referredUserId}/cancel`, {
      method: 'POST',
      token,
      body: { reason },
    });
  },
  saveFleetConfig(token: string, body: FleetConfig): Promise<FleetSettings> {
    return request<FleetSettings>('/admin/riders/settings/fleet', { method: 'PUT', token, body });
  },
  // --- rider applications (self sign-up), admin only ---
  /** Oldest submitted first: whoever has waited longest is at the top. */
  listRiderApplications(
    token: string,
    query: { status?: ApplicationStatus; q?: string; city?: string } = {},
  ): Promise<RiderApplicationSummary[]> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value) params.set(key, value);
    }
    const search = params.toString();
    return request<RiderApplicationSummary[]>(`/admin/rider-applications${search ? `?${search}` : ''}`, { token });
  },
  getRiderApplication(token: string, riderUserId: string): Promise<RiderApplicationDetail> {
    return request<RiderApplicationDetail>(`/admin/rider-applications/${riderUserId}`, { token });
  },
  acceptApplicationItem(token: string, riderUserId: string, kind: ItemKind): Promise<RiderApplicationDetail> {
    return request<RiderApplicationDetail>(`/admin/rider-applications/${riderUserId}/items/${kind}/accept`, { method: 'POST', token });
  },
  flagApplicationItem(token: string, riderUserId: string, kind: ItemKind, reason: string): Promise<RiderApplicationDetail> {
    return request<RiderApplicationDetail>(`/admin/rider-applications/${riderUserId}/items/${kind}/flag`, {
      method: 'POST',
      token,
      body: { reason },
    });
  },
  sendBackApplication(token: string, riderUserId: string): Promise<RiderApplicationDetail> {
    return request<RiderApplicationDetail>(`/admin/rider-applications/${riderUserId}/send-back`, { method: 'POST', token });
  },
  approveApplication(token: string, riderUserId: string): Promise<RiderApplicationDetail> {
    return request<RiderApplicationDetail>(`/admin/rider-applications/${riderUserId}/approve`, { method: 'POST', token });
  },
  rejectApplication(token: string, riderUserId: string, reason: string): Promise<RiderApplicationDetail> {
    return request<RiderApplicationDetail>(`/admin/rider-applications/${riderUserId}/reject`, {
      method: 'POST',
      token,
      body: { reason },
    });
  },
  reopenApplication(token: string, riderUserId: string): Promise<RiderApplicationDetail> {
    return request<RiderApplicationDetail>(`/admin/rider-applications/${riderUserId}/reopen`, { method: 'POST', token });
  },
  listUnpaidRiders(token: string): Promise<RiderUnpaid[]> {
    return request<RiderUnpaid[]>('/admin/riders/payouts/unpaid', { token });
  },
  payRider(token: string, userId: string, body: { period_to: string; reference: string }): Promise<RiderPayoutRecord> {
    return request<RiderPayoutRecord>(`/admin/riders/${userId}/payouts`, { method: 'POST', token, body });
  },
  getFleetDelivery(token: string, orderId: string): Promise<FleetDeliveryView> {
    return request<FleetDeliveryView>(`/admin/riders/deliveries/${orderId}`, { token });
  },
  reassignFleetDelivery(token: string, orderId: string, riderUserId: string): Promise<FleetDeliveryView> {
    return request<FleetDeliveryView>(`/admin/riders/deliveries/${orderId}/reassign`, {
      method: 'POST',
      token,
      body: { rider_user_id: riderUserId },
    });
  },
  confirmFleetDelivered(token: string, orderId: string, reason: string): Promise<FleetDeliveryView> {
    return request<FleetDeliveryView>(`/admin/riders/deliveries/${orderId}/confirm-delivered`, {
      method: 'POST',
      token,
      body: { reason },
    });
  },
  getAdminDashboard(token: string): Promise<AdminDashboardStats> {
    return request<AdminDashboardStats>('/admin/dashboard', { token });
  },
  getReports(
    token: string,
    filters: {
      dateFrom?: string | null;
      dateTo?: string | null;
      restaurantId?: string | null;
      cuisineType?: string | null;
      category?: string | null;
      orderStatus?: OrderStatus | null;
    },
  ): Promise<ReportsSnapshot> {
    const params = new URLSearchParams();
    if (filters.dateFrom) {
      params.set('date_from', filters.dateFrom);
    }
    if (filters.dateTo) {
      params.set('date_to', filters.dateTo);
    }
    if (filters.restaurantId) {
      params.set('restaurant_id', filters.restaurantId);
    }
    if (filters.cuisineType) {
      params.set('cuisine_type', filters.cuisineType);
    }
    if (filters.category) {
      params.set('category', filters.category);
    }
    if (filters.orderStatus) {
      params.set('order_status', filters.orderStatus);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<ReportsSnapshot>(`/reports${suffix}`, { token });
  },
  // --- preference questionnaire -----------------------------------------
  getPreferenceQuestions(token: string): Promise<AdminPreferenceQuestion[]> {
    return request<AdminPreferenceQuestion[]>('/admin/preferences/questions', { token });
  },
  createPreferenceQuestion(
    token: string,
    payload: PreferenceQuestionDraft,
  ): Promise<AdminPreferenceQuestion> {
    return request<AdminPreferenceQuestion>('/admin/preferences/questions', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  updatePreferenceQuestion(
    token: string,
    questionId: string,
    payload: Partial<PreferenceQuestionDraft>,
  ): Promise<AdminPreferenceQuestion> {
    return request<AdminPreferenceQuestion>(
      `/admin/preferences/questions/${encodeURIComponent(questionId)}`,
      { method: 'PATCH', token, body: payload },
    );
  },
  deletePreferenceQuestion(token: string, questionId: string): Promise<void> {
    return request<void>(
      `/admin/preferences/questions/${encodeURIComponent(questionId)}`,
      { method: 'DELETE', token },
    );
  },
  /** Hide or restore an inherited question, for this restaurant only. */
  setPreferenceQuestionVisibility(
    token: string,
    questionId: string,
    isHidden: boolean,
  ): Promise<AdminPreferenceQuestion> {
    return request<AdminPreferenceQuestion>(
      `/admin/preferences/questions/${encodeURIComponent(questionId)}/visibility`,
      { method: 'POST', token, body: { is_hidden: isHidden } },
    );
  },
  reorderPreferenceQuestions(
    token: string,
    ids: string[],
  ): Promise<AdminPreferenceQuestion[]> {
    return request<AdminPreferenceQuestion[]>('/admin/preferences/questions/reorder', {
      method: 'POST',
      token,
      body: { ids },
    });
  },
  createPreferenceOption(
    token: string,
    questionId: string,
    payload: PreferenceOptionDraft,
  ): Promise<AdminPreferenceOption> {
    return request<AdminPreferenceOption>(
      `/admin/preferences/questions/${encodeURIComponent(questionId)}/options`,
      { method: 'POST', token, body: payload },
    );
  },
  updatePreferenceOption(
    token: string,
    optionId: string,
    payload: Partial<PreferenceOptionDraft>,
  ): Promise<AdminPreferenceOption> {
    return request<AdminPreferenceOption>(
      `/admin/preferences/options/${encodeURIComponent(optionId)}`,
      { method: 'PATCH', token, body: payload },
    );
  },
  deletePreferenceOption(token: string, optionId: string): Promise<void> {
    return request<void>(`/admin/preferences/options/${encodeURIComponent(optionId)}`, {
      method: 'DELETE',
      token,
    });
  },
  reorderPreferenceOptions(
    token: string,
    questionId: string,
    ids: string[],
  ): Promise<AdminPreferenceOption[]> {
    return request<AdminPreferenceOption[]>(
      `/admin/preferences/questions/${encodeURIComponent(questionId)}/options/reorder`,
      { method: 'POST', token, body: { ids } },
    );
  },
  /**
   * Every restaurant, leaving out demo ones unless `includeDemo` - which only
   * the Restaurants page asks for, so a demo kitchen can be found and unmarked.
   */
  getAdminRestaurants(token: string, options?: { includeDemo?: boolean }): Promise<Restaurant[]> {
    const query = options?.includeDemo ? '?include_demo=true' : '';
    return request<Restaurant[]>(`/admin/restaurants${query}`, { token });
  },
  updateRestaurantDemo(token: string, restaurantId: string, isDemo: boolean): Promise<Restaurant> {
    return request<Restaurant>(`/admin/restaurants/${restaurantId}/demo`, {
      method: 'PATCH',
      token,
      body: { is_demo: isDemo },
    });
  },
  getAdminMenuItems(token: string): Promise<AdminMenuItem[]> {
    return request<AdminMenuItem[]>('/admin/menu-items', { token });
  },
  getAdminAILogs(token: string): Promise<AdminAILog[]> {
    return request<AdminAILog[]>('/admin/ai-logs', { token });
  },
  triggerAdminAIOfferGeneration(
    token: string,
    payload: {
      user_limit?: number | null;
      batch_size?: number | null;
      force_refresh?: boolean;
    } = {},
  ): Promise<AdminAIOfferGenerationTriggerResponse> {
    return request<AdminAIOfferGenerationTriggerResponse>('/admin/offers/generate-ai', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  /**
   * Generates offers for the signed-in owner's own restaurant.
   *
   * Separate from the admin trigger rather than a parameter on it: the scope is
   * resolved server-side from the session, so there is deliberately no
   * restaurant field an owner could set to widen the run.
   */
  triggerOwnerAIOfferGeneration(
    token: string,
    payload: {
      user_limit?: number | null;
      batch_size?: number | null;
      force_refresh?: boolean;
    } = {},
  ): Promise<AdminAIOfferGenerationTriggerResponse> {
    return request<AdminAIOfferGenerationTriggerResponse>('/owner/offers/generate-ai', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  getOwnerAIOfferGenerationStatus(
    token: string,
    taskId: string,
  ): Promise<AdminAIOfferGenerationStatusResponse> {
    return request<AdminAIOfferGenerationStatusResponse>(
      `/owner/offers/generate-ai/${taskId}`,
      { token },
    );
  },
  getAdminAIOfferGenerationStatus(
    token: string,
    taskId: string,
  ): Promise<AdminAIOfferGenerationStatusResponse> {
    return request<AdminAIOfferGenerationStatusResponse>(`/admin/offers/generate-ai/${taskId}`, { token });
  },
  getManagedGeneratedCombos(token: string, restaurantId?: string, locationId?: string | null): Promise<GeneratedCombo[]> {
    const params = new URLSearchParams();
    if (restaurantId) {
      params.set('restaurant_id', restaurantId);
    }
    if (locationId) {
      params.set('location_id', locationId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<GeneratedCombo[]>(`/admin/generated-combos${suffix}`, { token });
  },
  getRestaurantLocations(token: string, restaurantId: string): Promise<RestaurantLocation[]> {
    return request<RestaurantLocation[]>(`/restaurants/${restaurantId}/locations`, {token});
  },

  /**
   * The kitchen accounts for one restaurant.
   *
   * `restaurantId` is for an ADMIN, who has no restaurant of their own and
   * gets `400 restaurant_id is required` without one. An OWNER must pass null:
   * the backend resolves their restaurant from `Restaurant.owner_id`, and
   * naming one that disagrees is refused with 403. That asymmetry is
   * `resolve_order_board_scope`'s, not this panel's — see CLAUDE.md.
   */
  getKitchenStaff(token: string, restaurantId: string | null): Promise<KitchenStaff[]> {
    const suffix = restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : '';
    return request<KitchenStaff[]>(`/kitchen-staff${suffix}`, { token });
  },

  // --- Printing -----------------------------------------------------------
  //
  // `restaurantId` is the same asymmetry as everywhere else in this panel: an
  // ADMIN must name a restaurant and an OWNER must not, because
  // `resolve_insights_scope` requires one from the first and refuses one from
  // the second. See CLAUDE.md.

  getPrintAgents(token: string, restaurantId: string | null): Promise<PrintAgentDto[]> {
    const suffix = restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : '';
    return request<PrintAgentDto[]>(`/printing/agents${suffix}`, { token });
  },

  /**
   * A six-digit code for somebody standing at the kitchen PC.
   *
   * Short-lived and single-use, because this is the one moment a long-lived
   * agent credential comes into existence.
   */
  createPairingCode(
    token: string,
    payload: { restaurant_location_id: string; name: string; restaurant_id: string | null },
  ): Promise<PairingCodeDto> {
    return request<PairingCodeDto>('/printing/pairing-code', {
      method: 'POST',
      token,
      body: payload,
    });
  },

  addPrinter(
    token: string,
    agentId: string,
    payload: Record<string, unknown>,
    restaurantId: string | null,
  ): Promise<PrinterDto> {
    const suffix = restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : '';
    return request<PrinterDto>(`/printing/agents/${agentId}/printers${suffix}`, {
      method: 'POST',
      token,
      body: payload,
    });
  },

  updatePrinter(
    token: string,
    printerId: string,
    payload: Record<string, unknown>,
    restaurantId: string | null,
  ): Promise<PrinterDto> {
    const suffix = restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : '';
    return request<PrinterDto>(`/printing/printers/${printerId}${suffix}`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },

  /** Queue a page that proves this printer works. Always a second copy. */
  testPrint(
    token: string,
    printerId: string,
    restaurantId: string | null,
  ): Promise<PrintJobDto> {
    const suffix = restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : '';
    return request<PrintJobDto>(`/printing/printers/${printerId}/test${suffix}`, {
      method: 'POST',
      token,
      body: {},
    });
  },

  /** Recent tickets, including the ones that failed and why. */
  getPrintJobs(
    token: string,
    restaurantId: string | null,
    limit = 50,
  ): Promise<PrintJobDto[]> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (restaurantId) query.set('restaurant_id', restaurantId);
    return request<PrintJobDto[]>(`/printing/jobs?${query.toString()}`, { token });
  },

  reprintOrder(
    token: string,
    orderId: string,
    kind: string,
    restaurantId: string | null,
  ): Promise<PrintJobDto[]> {
    const query = new URLSearchParams({ kind });
    if (restaurantId) query.set('restaurant_id', restaurantId);
    return request<PrintJobDto[]>(`/printing/orders/${orderId}/reprint?${query.toString()}`, {
      method: 'POST',
      token,
      body: {},
    });
  },

  /**
   * Rename or switch off an agent.
   *
   * Switching off bumps `token_version`, so the PC stops on its next poll
   * rather than whenever its token would have expired. There is no delete:
   * `print_jobs` points at these rows.
   */
  updatePrintAgent(
    token: string,
    agentId: string,
    params: { is_enabled?: boolean; name?: string },
    restaurantId: string | null,
  ): Promise<PrintAgentDto> {
    const query = new URLSearchParams();
    if (params.is_enabled !== undefined) query.set('is_enabled', String(params.is_enabled));
    if (params.name !== undefined) query.set('name', params.name);
    if (restaurantId) query.set('restaurant_id', restaurantId);
    return request<PrintAgentDto>(`/printing/agents/${agentId}?${query.toString()}`, {
      method: 'PATCH',
      token,
      body: {},
    });
  },

  createKitchenStaff(
    token: string,
    payload: KitchenStaffCreatePayload,
  ): Promise<KitchenStaff> {
    return request<KitchenStaff>('/kitchen-staff', { method: 'POST', token, body: payload });
  },

  /**
   * Rename, reassign a branch, or activate/deactivate.
   *
   * Never the email or the password: the backend refuses both, because
   * re-pointing a live login at a different person is how a revoked account
   * quietly comes back. Deactivate and create another instead.
   */
  updateKitchenStaff(
    token: string,
    staffId: string,
    payload: KitchenStaffUpdatePayload,
    restaurantId: string | null,
  ): Promise<KitchenStaff> {
    const suffix = restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : '';
    return request<KitchenStaff>(`/kitchen-staff/${staffId}${suffix}`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  getRestaurantMenuItems(
    token: string,
    restaurantId: string,
    locationId?: string | null,
  ): Promise<MenuItem[]> {
    const params = new URLSearchParams({
      restaurant_id: restaurantId,
      include_unavailable: 'true',
    });
    if (locationId) {
      params.set('location_id', locationId);
    }
    return request<MenuItem[]>(`/menu-items?${params.toString()}`, { token });
  },
  getRestaurantOffers(token: string, restaurantId: string): Promise<ManagedPersonalizedOffer[]> {
    return request<ManagedPersonalizedOffer[]>(`/restaurants/${restaurantId}/offers`, { token });
  },
  createRestaurantOffer(
    token: string,
    restaurantId: string,
    payload: {
      name: string;
      offer_type: string;
      state: string;
      restaurant_location_id?: string | null;
      applicable_item_id?: string | null;
      applicable_category?: string | null;
      applicable_cuisine?: string | null;
      discount_type: string;
      discount_value: number;
      max_discount_amount?: number | null;
      minimum_order_amount: number;
      inactivity_days: number;
      cooldown_hours: number;
      valid_for_days: number;
      cta_label?: string | null;
      business_rules?: Record<string, unknown>;
      notes?: string | null;
      starts_at?: string | null;
      expires_at?: string | null;
    },
  ): Promise<ManagedPersonalizedOffer> {
    return request<ManagedPersonalizedOffer>(`/restaurants/${restaurantId}/offers`, {
      method: 'POST',
      token,
      body: payload,
    });
  },
  updateRestaurantOffer(
    token: string,
    restaurantId: string,
    offerId: string,
    payload: {
      name: string;
      offer_type: string;
      state: string;
      restaurant_location_id?: string | null;
      applicable_item_id?: string | null;
      applicable_category?: string | null;
      applicable_cuisine?: string | null;
      discount_type: string;
      discount_value: number;
      max_discount_amount?: number | null;
      minimum_order_amount: number;
      inactivity_days: number;
      cooldown_hours: number;
      valid_for_days: number;
      cta_label?: string | null;
      business_rules?: Record<string, unknown>;
      notes?: string | null;
      starts_at?: string | null;
      expires_at?: string | null;
    },
  ): Promise<ManagedPersonalizedOffer> {
    return request<ManagedPersonalizedOffer>(`/restaurants/${restaurantId}/offers/${offerId}`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  deleteRestaurantOffer(
    token: string,
    restaurantId: string,
    offerId: string,
  ): Promise<void> {
    return request<void>(`/restaurants/${restaurantId}/offers/${offerId}`, {
      method: 'DELETE',
      token,
    });
  },
  getGeneratedOfferMatches(
    token: string,
    restaurantId: string,
    generatedOfferId: string,
  ): Promise<GeneratedOfferUserMatch[]> {
    return request<GeneratedOfferUserMatch[]>(
      `/restaurants/${restaurantId}/generated-offers/${generatedOfferId}/matches`,
      { token },
    );
  },
  updateGeneratedOfferState(
    token: string,
    restaurantId: string,
    generatedOfferId: string,
    payload: {
      state?: string | null;
      title?: string | null;
      subtitle?: string | null;
      badge?: string | null;
      cta_label?: string | null;
      starts_at?: string | null;
      expires_at?: string | null;
    },
  ): Promise<ManagedPersonalizedOffer> {
    return request<ManagedPersonalizedOffer>(
      `/restaurants/${restaurantId}/generated-offers/${generatedOfferId}`,
      {
        method: 'PATCH',
        token,
        body: payload,
      },
    );
  },
  deleteGeneratedOffer(
    token: string,
    restaurantId: string,
    generatedOfferId: string,
  ): Promise<void> {
    return request<void>(`/restaurants/${restaurantId}/generated-offers/${generatedOfferId}`, {
      method: 'DELETE',
      token,
    });
  },
  createRestaurantLocation(
    token: string,
    restaurantId: string,
    payload: {
      branch_name: string;
      address_line_1: string;
      address_line_2?: string | null;
      city: string;
      state: string;
      postal_code: string;
      latitude?: number | null;
      longitude?: number | null;
      phone_number?: string | null;
      delivery_fee: number;
      minimum_order_amount: number;
      estimated_delivery_time: number;
      estimated_pickup_time?: number;
      delivery_enabled?: boolean;
      pickup_enabled?: boolean;
      is_open: boolean;
      is_active: boolean;
      temporary_closed_reason?: string | null;
      preparation_time_minutes?: number | null;
      service_radius_km?: number | null;
      opening_time?: string | null;
      closing_time?: string | null;
    },
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(`/restaurants/${restaurantId}/locations`, {
      method: 'POST',
      token,
      body: payload,
    });
  },
  updateRestaurantLocation(
    token: string,
    restaurantId: string,
    locationId: string,
    payload: Record<string, unknown>,
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(`/restaurants/${restaurantId}/locations/${locationId}`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  /**
   * Ask the server to find this branch's coordinates from its own address.
   *
   * Answers; does not save. A geocoder never refuses — it returns the middle of
   * the city for an address it does not know — so the owner sees what was found
   * and how precise it is before committing it.
   */
  locateRestaurantLocation(
    token: string,
    restaurantId: string,
    locationId: string,
  ): Promise<BranchLocationLookup> {
    return request<BranchLocationLookup>(
      `/restaurants/${restaurantId}/locations/${locationId}/locate`,
      { method: 'POST', token },
    );
  },
  getRestaurantLocationGeneralSettings(
    token: string,
    restaurantId: string,
    locationId: string,
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(
      `/restaurants/${restaurantId}/locations/${locationId}/general-settings`,
      { token },
    );
  },
  updateRestaurantLocationGeneralSettings(
    token: string,
    restaurantId: string,
    locationId: string,
    payload: Record<string, unknown>,
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(
      `/restaurants/${restaurantId}/locations/${locationId}/general-settings`,
      {
        method: 'PATCH',
        token,
        body: payload,
      },
    );
  },
  getRestaurantLocationSlots(
    token: string,
    restaurantId: string,
    locationId: string,
  ): Promise<LocationFulfillmentSlot[]> {
    return request<LocationFulfillmentSlot[]>(
      `/restaurants/${restaurantId}/locations/${locationId}/slots`,
      { token },
    );
  },
  createRestaurantLocationSlot(
    token: string,
    restaurantId: string,
    locationId: string,
    payload: {
      day_of_week: string;
      fulfillment_type: 'DELIVERY' | 'PICKUP';
      start_time: string;
      end_time: string;
      is_active?: boolean;
    },
  ): Promise<LocationFulfillmentSlot> {
    return request<LocationFulfillmentSlot>(
      `/restaurants/${restaurantId}/locations/${locationId}/slots`,
      {
        method: 'POST',
        token,
        body: payload,
      },
    );
  },
  updateRestaurantLocationSlot(
    token: string,
    restaurantId: string,
    locationId: string,
    slotId: string,
    payload: Record<string, unknown>,
  ): Promise<LocationFulfillmentSlot> {
    return request<LocationFulfillmentSlot>(
      `/restaurants/${restaurantId}/locations/${locationId}/slots/${slotId}`,
      {
        method: 'PATCH',
        token,
        body: payload,
      },
    );
  },
  deleteRestaurantLocationSlot(
    token: string,
    restaurantId: string,
    locationId: string,
    slotId: string,
  ): Promise<LocationFulfillmentSlot> {
    return request<LocationFulfillmentSlot>(
      `/restaurants/${restaurantId}/locations/${locationId}/slots/${slotId}`,
      {
        method: 'DELETE',
        token,
      },
    );
  },
  deactivateRestaurantLocation(
    token: string,
    restaurantId: string,
    locationId: string,
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(`/restaurants/${restaurantId}/locations/${locationId}`, {
      method: 'DELETE',
      token,
    });
  },
  rebuildAdminGeneratedCombos(
    token: string,
    lookbackDays?: number,
  ): Promise<{
    created_count: number;
    updated_count: number;
    deactivated_count: number;
    scanned_order_count: number;
    eligible_pattern_count: number;
  }> {
    const suffix = lookbackDays ? `?lookback_days=${lookbackDays}` : '';
    return request(`/admin/generated-combos/rebuild${suffix}`, {
      method: 'POST',
      token,
    });
  },
  updateGeneratedComboStatus(
    token: string,
    comboId: string,
    status: 'DRAFT' | 'LIVE' | 'ARCHIVED',
  ): Promise<GeneratedCombo> {
    return request<GeneratedCombo>(`/admin/generated-combos/${comboId}/status`, {
      method: 'PATCH',
      token,
      body: { status },
    });
  },
  getAdminRestaurant(token: string, restaurantId: string): Promise<RestaurantDetail> {
    return request<RestaurantDetail>(`/admin/restaurants/${restaurantId}`, { token });
  },
  getRestaurant(token: string, restaurantId: string): Promise<RestaurantDetail> {
    return request<RestaurantDetail>(`/restaurants/${restaurantId}`, { token });
  },
  updateRestaurantSettings(
    token: string,
    restaurantId: string,
    payload: {
      name?: string;
      description?: string | null;
      cuisine_type?: string;
      address_line_1?: string;
      address_line_2?: string | null;
      city?: string;
      state?: string;
      country?: string;
      postal_code?: string;
      phone_number?: string | null;
      logo_image_url?: string | null;
      cover_image_url?: string | null;
      is_open?: boolean;
      is_active?: boolean;
      /**
       * ADMIN only — the server refuses it from an owner.
       *
       * Relabels every price this restaurant shows and every charge it makes;
       * it converts nothing. Orders already placed keep the currency they
       * were charged in, which is why `orders.currency` is stamped per order.
       */
      currency?: string;
    },
  ): Promise<RestaurantDetail> {
    return request<RestaurantDetail>(`/restaurants/${restaurantId}/settings`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  updateRestaurantApproval(token: string, restaurantId: string, isApproved: boolean): Promise<Restaurant> {
    return request<Restaurant>(`/admin/restaurants/${restaurantId}/approval`, {
      method: 'PATCH',
      token,
      body: { is_approved: isApproved },
    });
  },
  updateRestaurant(
    token: string,
    restaurantId: string,
    payload: {
      name: string;
      description?: string | null;
      cuisine_type: string;
      address_line_1: string;
      address_line_2?: string | null;
      city: string;
      state: string;
      country: string;
      postal_code: string;
      phone_number?: string | null;
      minimum_order_amount: number;
      delivery_fee: number;
      logo_image_url?: string | null;
      cover_image_url?: string | null;
      is_open: boolean;
    },
  ): Promise<Restaurant> {
    return request<Restaurant>(`/admin/restaurants/${restaurantId}`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  deleteRestaurant(token: string, restaurantId: string): Promise<void> {
    return request<void>(`/admin/restaurants/${restaurantId}`, { method: 'DELETE', token });
  },
  /**
   * One page of the accounts this session may see, filtered on the server,
   * with the full count from `X-Total-Count` (2026-10-07 security review:
   * this used to fetch every account for the page to filter).
   */
  async getAdminUsers(
    token: string,
    opts: {
      page: number;
      pageSize: number;
      search?: string;
      role?: UserRole | null;
      status?: 'ACTIVE' | 'INACTIVE' | null;
    },
  ): Promise<{ rows: User[]; total: number }> {
    const params = new URLSearchParams({
      limit: String(opts.pageSize),
      offset: String((opts.page - 1) * opts.pageSize),
    });
    if (opts.search) params.set('search', opts.search);
    if (opts.role) params.set('role', opts.role);
    if (opts.status) params.set('status', opts.status);
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    const response = await fetch(`${API_BASE_URL}/admin/users?${params.toString()}`, { headers });
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_INVALID_EVENT));
      throw new ApiError('Your session has expired. Please sign in again.', 401);
    }
    const payload = await response.json().catch(() => []);
    if (!response.ok) {
      const detail = typeof payload.detail === 'string' ? payload.detail : 'Unable to load users.';
      throw new ApiError(detail, response.status);
    }
    return { rows: payload as User[], total: Number(response.headers.get('X-Total-Count') ?? payload.length) };
  },
  /** Accounts per role, for the tiles - everybody, not the page on screen. */
  getAdminUserStats(token: string): Promise<AdminUserStats> {
    return request<AdminUserStats>('/admin/users/stats', { token });
  },
  getAdminUser(token: string, userId: string): Promise<User> {
    return request<User>(`/admin/users/${userId}`, { token });
  },
  updateAdminUserDetails(
    token: string,
    userId: string,
    payload: { full_name: string; phone_number: string | null; default_address: string | null },
  ): Promise<User> {
    return request<User>(`/admin/users/${userId}/details`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  updateUserStatus(token: string, userId: string, isActive: boolean): Promise<User> {
    return request<User>(`/admin/users/${userId}`, {
      method: 'PATCH',
      token,
      body: { is_active: isActive },
    });
  },
  sendNotification(
    token: string,
    payload: SendNotificationPayload,
  ): Promise<SendNotificationResponse> {
    return request<SendNotificationResponse>('/admin/notifications/send', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  getNotificationHistory(token: string): Promise<NotificationHistoryItem[]> {
    return request<NotificationHistoryItem[]>('/admin/notifications/history', {
      token,
    });
  },
  getOwnerRestaurants(token: string): Promise<Restaurant[]> {
    return request<Restaurant[]>('/restaurants/mine', { token });
  },
  createRestaurant(
    token: string,
    payload: AdminCreateRestaurantPayload,
  ): Promise<AdminCreateRestaurantResult> {
    return request<AdminCreateRestaurantResult>('/restaurants', { method: 'POST', token, body: payload });
  },
  /** Resolves to null when the restaurant has no app client yet. */
  async getRestaurantAppClient(token: string, restaurantId: string): Promise<AppClient | null> {
    try {
      return await request<AppClient>(`/restaurants/${restaurantId}/app-client`, { token });
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },
  saveRestaurantAppClient(
    token: string,
    restaurantId: string,
    payload: AppClientUpsertPayload,
  ): Promise<AppClient> {
    return request<AppClient>(`/restaurants/${restaurantId}/app-client`, {
      method: 'PUT',
      token,
      body: payload,
    });
  },
  /** Every tenant on the platform. ADMIN only; an owner gets a 403. */
  listTenants(token: string): Promise<TenantSummary[]> {
    return request<TenantSummary[]>('/app-clients', { token });
  },
  /**
   * Suspend, offboard or reactivate a tenant.
   *
   * The server refuses anything other than ACTIVE without a note, and refuses
   * to revive an offboarded tenant at all — both deliberately, so the UI can
   * ask plainly rather than guard silently.
   */
  updateTenantStatus(
    token: string,
    tenantId: string,
    payload: TenantStatusPayload,
  ): Promise<TenantSummary> {
    return request<TenantSummary>(`/app-clients/${tenantId}/status`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  /**
   * What the courier is doing with this order, or null if nobody was asked.
   *
   * Behind the same reader as the order itself: a delivery carries a rider's
   * phone number, and whoever may not read the order may not read that.
   */
  getOrderDelivery(token: string, orderId: string): Promise<OrderDelivery | null> {
    return request<OrderDelivery | null>(`/orders/${orderId}/delivery`, { token });
  },
  /** Call the rider off while the order stands. Refused once the food is collected. */
  cancelOrderDelivery(token: string, orderId: string): Promise<OrderDelivery | null> {
    return request<OrderDelivery | null>(`/orders/${orderId}/delivery/cancel`, { method: 'POST', token });
  },
  /** Book another rider after the last trip failed or was called off. */
  /** Ask the courier's networks again for a rider, for a booking nobody took. */
  allocateOrderDelivery(token: string, orderId: string): Promise<OrderDelivery | null> {
    return request<OrderDelivery | null>(`/orders/${orderId}/delivery/allocate`, { method: 'POST', token });
  },
  rebookOrderDelivery(token: string, orderId: string): Promise<OrderDelivery | null> {
    return request<OrderDelivery | null>(`/orders/${orderId}/delivery/rebook`, { method: 'POST', token });
  },
  /** Sandbox only, admin only: make the courier report a stage. */
  simulateOrderDelivery(token: string, orderId: string, status: string): Promise<OrderDelivery | null> {
    return request<OrderDelivery | null>(`/orders/${orderId}/delivery/simulate`, {
      method: 'POST',
      token,
      body: { status },
    });
  },
  /** What this restaurant has switched on, and why. Owners may read it too. */
  getRestaurantCapabilities(token: string, restaurantId: string): Promise<RestaurantCapability[]> {
    return request<RestaurantCapability[]>(`/restaurants/${restaurantId}/capabilities`, { token });
  },
  /**
   * Switch one capability for one restaurant. ADMIN only.
   *
   * `enabled: null` clears the decision and returns this restaurant to the
   * platform default, which is a different fact from switching it off.
   */
  setRestaurantCapability(
    token: string,
    restaurantId: string,
    key: string,
    payload: { enabled: boolean | null; note?: string | null },
  ): Promise<RestaurantCapability[]> {
    return request<RestaurantCapability[]>(
      `/restaurants/${restaurantId}/capabilities/${encodeURIComponent(key)}`,
      { method: 'PUT', token, body: payload },
    );
  },
  /** Which gateways this restaurant holds, and which buttons its customers see. */
  getRestaurantPaymentSettings(token: string, restaurantId: string): Promise<RestaurantPaymentSettings> {
    return request<RestaurantPaymentSettings>(`/restaurants/${restaurantId}/payment-settings`, { token });
  },
  /**
   * Store or update one gateway. ADMIN only.
   *
   * Leave `secret_key` out to keep the stored one — the screen cannot show it,
   * so an empty field means "unchanged", never "clear it".
   */
  saveRestaurantPaymentGateway(
    token: string,
    restaurantId: string,
    gateway: PaymentGateway,
    payload: PaymentGatewayPayload,
  ): Promise<RestaurantPaymentSettings> {
    return request<RestaurantPaymentSettings>(
      `/restaurants/${restaurantId}/payment-settings/${gateway}`,
      { method: 'PUT', token, body: payload },
    );
  },
  /** Forget a gateway's credentials. Distinct from switching it off. */
  deleteRestaurantPaymentGateway(
    token: string,
    restaurantId: string,
    gateway: PaymentGateway,
  ): Promise<RestaurantPaymentSettings> {
    return request<RestaurantPaymentSettings>(
      `/restaurants/${restaurantId}/payment-settings/${gateway}`,
      { method: 'DELETE', token },
    );
  },
  getMenuItems(token: string, restaurantId: string, locationId?: string | null): Promise<MenuItem[]> {
    const params = new URLSearchParams({
      restaurant_id: restaurantId,
      include_unavailable: 'true',
    });
    if (locationId) {
      params.set('location_id', locationId);
    }
    return request<MenuItem[]>(`/menu-items?${params.toString()}`, { token });
  },
  createMenuItem(
    token: string,
    payload: MenuItemUpsertPayload & {
      restaurant_id: string;
      restaurant_location_id?: string | null;
    },
  ): Promise<MenuItem> {
    return request<MenuItem>('/menu-items', { method: 'POST', token, body: payload });
  },
  createMenuItemsBulk(
    token: string,
    payload: MenuItemUpsertPayload & {
      restaurant_id: string;
      restaurant_location_ids: string[];
      skip_duplicates?: boolean;
    },
  ): Promise<MenuItemBulkCreateResult> {
    return request<MenuItemBulkCreateResult>('/menu-items/bulk', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  updateMenuItem(
    token: string,
    menuItemId: string,
    payload: MenuItemUpsertPayload & {
      restaurant_location_id?: string | null;
    },
  ): Promise<MenuItem> {
    return request<MenuItem>(`/menu-items/${menuItemId}`, { method: 'PUT', token, body: payload });
  },
  updateMenuItemAvailability(token: string, menuItemId: string, isAvailable: boolean): Promise<MenuItem> {
    return request<MenuItem>(`/menu-items/${menuItemId}/availability`, {
      method: 'PATCH',
      token,
      body: { is_available: isAvailable },
    });
  },
  /**
   * The one-tap stock change: mark a dish out of stock or back in, or set
   * its count. Only what is sent is changed.
   */
  updateMenuItemStock(
    token: string,
    menuItemId: string,
    change: { out_of_stock?: boolean; stock_quantity?: number | null },
  ): Promise<MenuItem> {
    return request<MenuItem>(`/menu-items/${menuItemId}/stock`, {
      method: 'PATCH',
      token,
      body: change,
    });
  },
  deleteMenuItem(token: string, menuItemId: string): Promise<void> {
    return request<void>(`/menu-items/${menuItemId}`, { method: 'DELETE', token });
  },
  getOrders(token: string, restaurantId?: string, locationId?: string | null): Promise<Order[]> {
    const params = new URLSearchParams();
    if (restaurantId) {
      params.set('restaurant_id', restaurantId);
    }
    if (locationId) {
      params.set('restaurant_location_id', locationId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<Order[]>(`/orders${suffix}`, { token });
  },
  async getOrdersPage(
    token: string,
    opts: {
      page: number;
      pageSize: number;
      search?: string;
      status?: OrderStatus | null;
      sort?: { id: string; direction: 'asc' | 'desc' } | null;
    },
  ): Promise<{ rows: Order[]; total: number }> {
    const params = new URLSearchParams({
      limit: String(opts.pageSize),
      offset: String((opts.page - 1) * opts.pageSize),
    });
    if (opts.search) {
      params.set('search', opts.search);
    }
    if (opts.status) {
      params.set('order_status', opts.status);
    }
    if (opts.sort) {
      params.set('sort', `${opts.sort.id}:${opts.sort.direction}`);
    }
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    const response = await fetch(`${API_BASE_URL}/orders?${params.toString()}`, { headers });
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_INVALID_EVENT));
      throw new ApiError('Your session has expired. Please sign in again.', 401);
    }
    const payload = await response.json().catch(() => []);
    if (!response.ok) {
      const detail = typeof payload.detail === 'string' ? payload.detail : 'Unable to load orders.';
      throw new ApiError(detail, response.status);
    }
    const total = Number(response.headers.get('X-Total-Count') ?? payload.length);
    return { rows: payload as Order[], total };
  },
  async getOrdersCount(
    token: string,
    opts: { search?: string; status?: OrderStatus | null } = {},
  ): Promise<number> {
    const params = new URLSearchParams({ limit: '1', offset: '0' });
    if (opts.search) {
      params.set('search', opts.search);
    }
    if (opts.status) {
      params.set('order_status', opts.status);
    }
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    const response = await fetch(`${API_BASE_URL}/orders?${params.toString()}`, { headers });
    if (!response.ok) {
      return 0;
    }
    await response.json().catch(() => null);
    return Number(response.headers.get('X-Total-Count') ?? 0);
  },
  /**
   * The live board: every open order in scope and what was delivered since
   * `completedFrom` — the viewer's own midnight, which the server cannot know.
   */
  getLiveOrders(
    token: string,
    opts: { completedFrom: Date; restaurantId?: string | null },
  ): Promise<LiveOrdersBoard> {
    const params = new URLSearchParams({ completed_from: opts.completedFrom.toISOString() });
    if (opts.restaurantId) {
      params.set('restaurant_id', opts.restaurantId);
    }
    return request<LiveOrdersBoard>(`/orders/live?${params.toString()}`, { token });
  },
  getOrder(token: string, orderId: string): Promise<Order> {
    return request<Order>(`/orders/${orderId}`, { token });
  },
  /** Cancel an order the rider has not collected; a prepaid one is refunded. */
  cancelOrder(token: string, orderId: string, reason: string, note: string): Promise<Order> {
    return request<Order>(`/orders/${orderId}/cancel`, {
      method: "POST",
      token,
      body: { reason, note },
    });
  },
  /** Try a refund the gateway refused again. */
  retryOrderRefund(token: string, orderId: string): Promise<Order> {
    return request<Order>(`/orders/${orderId}/refund/retry`, { method: "POST", token });
  },
  updateOrderStatus(token: string, orderId: string, status: OrderStatus): Promise<Order> {
    return request<Order>(`/orders/${orderId}/status`, {
      method: 'PATCH',
      token,
      body: { status },
    });
  },
  // --- AI Restaurant Manager ------------------------------------------------
  // `restaurantId` is required for ADMIN and ignored for OWNER: the backend
  // pins an owner to their own restaurant and rejects any other value.

  getOwnerBriefing(
    token: string,
    restaurantId?: string | null,
    // Naming a period returns a briefing for exactly that period, computed on
    // the spot. Without one the stored nightly briefing comes back, which may
    // describe a different window than the rest of the screen.
    options: { windowDays?: number | null } = {},
  ): Promise<OwnerBriefing> {
    const params = new URLSearchParams();
    if (restaurantId) {
      params.set('restaurant_id', restaurantId);
    }
    if (options.windowDays) {
      params.set('window_days', String(options.windowDays));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerBriefing>(`/owner/insights/briefing${suffix}`, { token });
  },
  getOwnerDiagnostics(
    token: string,
    options: {
      restaurantId?: string | null;
      windowDays?: number | null;
      // Used to align the KPI row with the briefing's own period. Without it the
      // two halves of the card can describe different windows.
      dateFrom?: string | null;
      dateTo?: string | null;
    } = {},
  ): Promise<DiagnosticsSnapshot> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.windowDays) {
      params.set('window_days', String(options.windowDays));
    }
    if (options.dateFrom) {
      params.set('date_from', options.dateFrom);
    }
    if (options.dateTo) {
      params.set('date_to', options.dateTo);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<DiagnosticsSnapshot>(`/owner/insights/diagnostics${suffix}`, { token });
  },
  getOwnerInsightFeed(
    token: string,
    // The period makes this and the briefing read from one analysis. Without
    // it the feed lists stored rows from whatever window the nightly run chose,
    // which is how a briefing could narrate findings the feed said did not exist.
    options: { restaurantId?: string | null; limit?: number; windowDays?: number | null } = {},
  ): Promise<OwnerInsight[]> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.windowDays) {
      params.set('window_days', String(options.windowDays));
    }
    if (options.limit) {
      params.set('limit', String(options.limit));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerInsight[]>(`/owner/insights/feed${suffix}`, { token });
  },
  updateOwnerInsightStatus(
    token: string,
    insightId: string,
    status: OwnerInsightStatus,
    restaurantId?: string | null,
  ): Promise<OwnerInsight> {
    return request<OwnerInsight>(
      `/owner/insights/feed/${insightId}${scopeQuery(restaurantId)}`,
      { method: 'PATCH', token, body: { status } },
    );
  },
  getOwnerRecommendations(
    token: string,
    options: { restaurantId?: string | null; statuses?: string[] } = {},
  ): Promise<OwnerActionProposal[]> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    for (const status of options.statuses ?? []) {
      params.append('action_status', status);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerActionProposal[]>(`/owner/insights/recommendations${suffix}`, {
      token,
    });
  },
  approveOwnerRecommendation(
    token: string,
    proposalId: string,
    restaurantId?: string | null,
  ): Promise<OwnerActionApproval> {
    return request<OwnerActionApproval>(
      `/owner/insights/recommendations/${proposalId}/approve${scopeQuery(restaurantId)}`,
      { method: 'POST', token },
    );
  },
  /**
   * Starts an offer this restaurant already has, from a chat card.
   *
   * Deliberately not `updateRestaurantOffer`: that takes a full upsert, so a
   * card would have to reconstruct every field of the offer to change one, and
   * any field it got wrong would be written silently.
   */
  activateSuggestedOffer(
    token: string,
    offerId: string,
    restaurantId?: string | null,
  ): Promise<SuggestionOfferActivation> {
    return request<SuggestionOfferActivation>(
      `/owner/insights/suggestions/offers/${offerId}/activate${scopeQuery(restaurantId)}`,
      { method: 'POST', token },
    );
  },
  getRestaurantStorefront(token: string, restaurantId: string): Promise<RestaurantStorefront> {
    return request<RestaurantStorefront>(`/restaurants/${restaurantId}/storefront`, { token });
  },
  /**
   * Only the keys you send are changed — the route uses `exclude_unset`, so an
   * omitted field keeps whatever the owner wrote elsewhere rather than being
   * cleared. Send a field as "" to deliberately clear it back to the derived
   * default.
   */
  updateRestaurantStorefront(
    token: string,
    restaurantId: string,
    payload: Partial<Record<StorefrontCopyKey, string>>,
  ): Promise<RestaurantStorefront> {
    return request<RestaurantStorefront>(`/restaurants/${restaurantId}/storefront`, {
      method: 'PUT',
      token,
      body: payload,
    });
  },
  getRestaurantBrand(token: string, restaurantId: string): Promise<RestaurantBrand> {
    return request<RestaurantBrand>(`/restaurants/${restaurantId}/brand`, { token });
  },
  /** Same rule as the storefront copy: an omitted half is left alone, and an
   *  empty list clears that half on purpose. */
  updateRestaurantBrand(
    token: string,
    restaurantId: string,
    payload: {
      about_sections?: BrandSection[];
      faqs?: BrandFaq[];
      established_year?: number | null;
      specialities?: string[];
      highlights?: BrandHighlight[];
    },
  ): Promise<RestaurantBrand> {
    return request<RestaurantBrand>(`/restaurants/${restaurantId}/brand`, {
      method: 'PUT',
      token,
      body: payload,
    });
  },
  getRestaurantTheme(token: string, restaurantId: string): Promise<RestaurantTheme> {
    return request<RestaurantTheme>(`/restaurants/${restaurantId}/theme`, { token });
  },
  updateRestaurantTheme(
    token: string,
    restaurantId: string,
    payload: { preset?: string | null; primary_color?: string | null },
  ): Promise<RestaurantTheme> {
    return request<RestaurantTheme>(`/restaurants/${restaurantId}/theme`, {
      method: 'PUT',
      token,
      body: payload,
    });
  },
  rejectOwnerRecommendation(
    token: string,
    proposalId: string,
    restaurantId?: string | null,
  ): Promise<OwnerActionProposal> {
    return request<OwnerActionProposal>(
      `/owner/insights/recommendations/${proposalId}/reject${scopeQuery(restaurantId)}`,
      { method: 'POST', token },
    );
  },
  getOwnerOfferPerformance(
    token: string,
    options: { restaurantId?: string | null; windowDays?: number | null } = {},
  ): Promise<OfferPerformanceSnapshot> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.windowDays) {
      params.set('window_days', String(options.windowDays));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OfferPerformanceSnapshot>(
      `/owner/insights/offer-performance${suffix}`,
      { token },
    );
  },
  getOwnerActionOutcomes(
    token: string,
    options: { restaurantId?: string | null; limit?: number } = {},
  ): Promise<ActionOutcome[]> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.limit) {
      params.set('limit', String(options.limit));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<ActionOutcome[]>(`/owner/insights/outcomes${suffix}`, { token });
  },
  sendOwnerChatMessage(
    token: string,
    input: { message: string; sessionId?: string | null; restaurantId?: string | null },
  ): Promise<OwnerChatAnswer> {
    return request<OwnerChatAnswer>('/owner/insights/chat/message', {
      method: 'POST',
      token,
      body: {
        message: input.message,
        session_id: input.sessionId ?? null,
        restaurant_id: input.restaurantId ?? null,
      },
    });
  },
  getOwnerChatHistory(
    token: string,
    options: { restaurantId?: string | null; sessionId?: string | null } = {},
  ): Promise<OwnerChatHistoryItem[]> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.sessionId) {
      params.set('session_id', options.sessionId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerChatHistoryItem[]>(`/owner/insights/chat/history${suffix}`, {
      token,
    });
  },
  clearOwnerChatHistory(
    token: string,
    options: { restaurantId?: string | null; sessionId?: string | null } = {},
  ): Promise<OwnerChatClearResult> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.sessionId) {
      params.set('session_id', options.sessionId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerChatClearResult>(`/owner/insights/chat/history${suffix}`, {
      method: 'DELETE',
      token,
    });
  },
};


export function toNumber(value: number | string): number {
  return typeof value === 'number' ? value : Number(value);
}

/**
 * How a currency is written, mirroring `services/currency.py`.
 *
 * `locale` carries the GROUPING rule rather than the symbol, and that is the
 * part that is easy to get wrong: Indian grouping is 2-2-3, so an `en-CA`
 * locale writes 12,34,567 as 1,234,567 — a number an Indian owner reads
 * twice before believing.
 */
const CURRENCY_FORMATS: Record<string, { locale: string; minDigits: number }> = {
  INR: { locale: 'en-IN', minDigits: 0 },
  USD: { locale: 'en-US', minDigits: 2 },
  CAD: { locale: 'en-CA', minDigits: 2 },
  GBP: { locale: 'en-GB', minDigits: 2 },
  EUR: { locale: 'en-IE', minDigits: 2 },
  AED: { locale: 'en-AE', minDigits: 2 },
};

/**
 * What the panel writes money in when nothing has told it otherwise.
 *
 * Rupees, because the platform is launching in India: every real restaurant
 * on it charges in INR. It was USD from the days of one Bangkok kitchen, and
 * a super admin looking at the platform as a whole read rupee takings under a
 * "$".
 */
export const DEFAULT_CURRENCY = 'INR';

function formatFor(code: string | null | undefined) {
  const resolved = (code || DEFAULT_CURRENCY).toUpperCase();
  return { code: resolved, ...(CURRENCY_FORMATS[resolved] ?? CURRENCY_FORMATS[DEFAULT_CURRENCY]) };
}

/**
 * The single place this panel decides what money looks like.
 *
 * `currency` is a parameter because one panel now shows several restaurants'
 * money: a Surat kitchen's ₹35 dhokla was rendering as "$35.00", which is the
 * right number under the wrong symbol. Prefer `useMoney()`, which binds this
 * to whichever restaurant the shell is scoped to; the bare call is for the
 * platform-wide surfaces, which have no single answer.
 */
export function formatCurrency(value: number | string, currency?: string | null): string {
  const format = formatFor(currency);
  const numeric = toNumber(value);
  // A currency written without its minor unit (rupees: "₹120") still shows
  // BOTH digits once there are paise - "₹8,412.50", never "₹8,412.5".
  const fraction = Math.round(numeric * 100) % 100 !== 0 ? 2 : format.minDigits;
  return new Intl.NumberFormat(format.locale, {
    style: 'currency',
    currency: format.code,
    minimumFractionDigits: fraction,
    maximumFractionDigits: 2,
  }).format(numeric);
}

/**
 * Money for a stat tile, where the column is narrow and the exact cent is not
 * the point: "$1.2K" rather than "$1,234.56".
 *
 * Lived twice, verbatim, in the dashboard and the reports page. One definition
 * so a currency change is one edit rather than a hunt.
 */
export function formatCompactCurrency(value: number | string, currency?: string | null): string {
  const numeric = toNumber(value);
  const format = formatFor(currency);
  return new Intl.NumberFormat(format.locale, {
    style: 'currency',
    currency: format.code,
    notation: 'compact',
    maximumFractionDigits: numeric >= 1000 ? 1 : 0,
  }).format(numeric);
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}
