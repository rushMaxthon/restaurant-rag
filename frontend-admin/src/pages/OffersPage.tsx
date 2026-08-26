import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Ban,
  CalendarX2,
  Edit3,
  Eye,
  FileEdit,
  PauseCircle,
  PlayCircle,
  Store,
  TicketPercent,
  Trash2,
} from "lucide-react";
import { Modal } from "../components/Modal";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataToolbar } from "../components/DataToolbar";
import { StatTiles, type StatTileItem } from "../components/StatTiles";
import { Pagination } from "../components/Pagination";
import { PageIntro } from "../components/PageIntro";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { StatusPill } from "../components/StatusPill";
import { pluralize } from "../services/format";
import { ApiError, api, formatCurrency, formatDate } from "../services/api";
import {
  getPageSnapshot,
  hasPageSnapshot,
  setPageSnapshot,
  tokenScope,
} from "../services/pageCache";
import type {
  GeneratedOfferUserMatch,
  ManagedPersonalizedOffer,
  PersonalizedOfferAudience,
  PersonalizedOfferDiscountType,
  PersonalizedOfferState,
  PersonalizedOfferType,
  Restaurant,
  RestaurantLocation,
  UserRole,
} from "../types/app";

interface OffersPageProps {
  token: string;
  role: UserRole;
  restaurantId: string | null;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

type OfferFormState = {
  restaurant_id: string;
  name: string;
  generated_subtitle: string;
  generated_badge: string;
  offer_type: PersonalizedOfferType;
  audience_type: PersonalizedOfferAudience;
  state: PersonalizedOfferState;
  restaurant_location_id: string;
  applicable_category: string;
  applicable_cuisine: string;
  discount_type: PersonalizedOfferDiscountType;
  discount_value: string;
  max_discount_amount: string;
  minimum_order_amount: string;
  cta_label: string;
  starts_at: string;
  expires_at: string;
  notes: string;
};

type OfferEditorKind = "TEMPLATE" | "GENERATED";

type RestaurantContext = {
  restaurant: Restaurant;
  locations: RestaurantLocation[];
};

type OfferRow = ManagedPersonalizedOffer & {
  restaurant_name: string;
  restaurant_slug: string;
  restaurant_city: string;
};

const OFFER_TYPE_OPTIONS: Array<{ value: PersonalizedOfferType; label: string }> = [
  { value: "FAVORITE_RESTAURANT", label: "Favorite restaurant" },
  { value: "FAVORITE_ITEM", label: "Repeated item" },
  { value: "ORDER_HISTORY_MATCH", label: "Order history match" },
  { value: "CUISINE_AFFINITY", label: "Cuisine affinity" },
  { value: "PREFERENCE_MATCH", label: "Preference match" },
  { value: "TASTE_MATCH", label: "Taste match" },
  { value: "COMBO_AFFINITY", label: "Combo affinity" },
  { value: "BUDGET_BEHAVIOR", label: "Budget behavior" },
  { value: "NEW_ITEM_MATCH", label: "New item match" },
  { value: "WELCOME_FIRST_ORDER", label: "First-order welcome" },
  { value: "CUSTOM", label: "Custom" },
];

const AUDIENCE_OPTIONS: Array<{ value: PersonalizedOfferAudience; label: string }> = [
  { value: "ALL_CUSTOMERS", label: "All customers" },
  { value: "ACTIVE_USERS", label: "Active users" },
  { value: "INACTIVE_USERS", label: "Inactive users" },
];

const OFFER_STATE_OPTIONS: Array<{ value: PersonalizedOfferState; label: string }> = [
  { value: "DRAFT", label: "Draft" },
  { value: "ACTIVE", label: "Active" },
  { value: "PAUSED", label: "Paused" },
  { value: "DISABLED", label: "Disabled" },
];

const DISCOUNT_TYPE_OPTIONS: Array<{ value: PersonalizedOfferDiscountType; label: string }> = [
  { value: "NONE", label: "No discount / info card" },
  { value: "PERCENTAGE", label: "Percentage" },
  { value: "FLAT", label: "Flat amount" },
  { value: "FREE_DELIVERY", label: "Free delivery" },
];

function emptyOfferForm(restaurantId: string): OfferFormState {
  return {
    restaurant_id: restaurantId,
    name: "",
    generated_subtitle: "",
    generated_badge: "",
    offer_type: "FAVORITE_RESTAURANT",
    audience_type: "ALL_CUSTOMERS",
    state: "DRAFT",
    restaurant_location_id: "",
    applicable_category: "",
    applicable_cuisine: "",
    discount_type: "NONE",
    discount_value: "0",
    max_discount_amount: "",
    minimum_order_amount: "0",
    cta_label: "",
    starts_at: "",
    expires_at: "",
    notes: "",
  };
}

function toDateTimeLocal(value: string | null): string {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

function fromOffer(offer: OfferRow): OfferFormState {
  return {
    restaurant_id: offer.restaurant_id,
    name: offer.record_kind === "GENERATED" ? (offer.generated_title ?? offer.name) : offer.name,
    generated_subtitle: offer.generated_subtitle ?? "",
    generated_badge: offer.generated_badge ?? "",
    offer_type: offer.offer_type,
    audience_type: offer.audience_type,
    state: offer.state,
    restaurant_location_id: offer.restaurant_location_id ?? "",
    applicable_category: offer.applicable_category ?? "",
    applicable_cuisine: offer.applicable_cuisine ?? "",
    discount_type: offer.discount_type,
    discount_value: String(offer.discount_value ?? 0),
    max_discount_amount: offer.max_discount_amount == null ? "" : String(offer.max_discount_amount),
    minimum_order_amount: String(offer.minimum_order_amount ?? 0),
    cta_label: offer.record_kind === "GENERATED" ? (offer.generated_cta_label ?? offer.cta_label ?? "") : (offer.cta_label ?? ""),
    starts_at: toDateTimeLocal(offer.starts_at),
    expires_at: toDateTimeLocal(offer.expires_at),
    notes: offer.notes ?? "",
  };
}

function buildGeneratedOfferPayload(form: OfferFormState, offer: OfferRow) {
  return {
    state: form.state,
    title: form.name.trim() || offer.generated_title || offer.name,
    subtitle: form.generated_subtitle.trim() || offer.generated_subtitle || "",
    badge: form.generated_badge.trim() || null,
    cta_label: form.cta_label.trim() || null,
    starts_at: form.starts_at ? new Date(form.starts_at).toISOString() : null,
    expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
  };
}

function buildPayload(form: OfferFormState) {
  return {
    name: form.name.trim(),
    offer_type: form.offer_type,
    audience_type: form.audience_type,
    state: form.state,
    restaurant_location_id: form.restaurant_location_id || null,
    applicable_item_id: null,
    applicable_category: form.applicable_category.trim() || null,
    applicable_cuisine: form.applicable_cuisine.trim() || null,
    discount_type: form.discount_type,
    discount_value: Number(form.discount_value || 0),
    max_discount_amount: form.max_discount_amount ? Number(form.max_discount_amount) : null,
    minimum_order_amount: Number(form.minimum_order_amount || 0),
    inactivity_days: 14,
    cooldown_hours: 48,
    valid_for_days: 7,
    cta_label: form.cta_label.trim() || null,
    business_rules: {},
    notes: form.notes.trim() || null,
    starts_at: form.starts_at ? new Date(form.starts_at).toISOString() : null,
    expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
  };
}

function buildQuickTogglePayload(
  offer: OfferRow,
  nextState: PersonalizedOfferState,
) {
  return {
    ...buildPayload(fromOffer(offer)),
    state: nextState,
  };
}

function formatOfferTypeLabel(value: PersonalizedOfferType): string {
  const option = OFFER_TYPE_OPTIONS.find((entry) => entry.value === value);
  return option?.label ?? value;
}

function describeOfferScope(offer: OfferRow): string {
  return (
    offer.applicable_item_name
    ?? offer.applicable_category
    ?? offer.applicable_cuisine
    ?? "Restaurant wide"
  );
}

function describeOfferSegment(offer: OfferRow): string {
  if (offer.offer_type === "WELCOME_FIRST_ORDER") {
    return "First order only";
  }
  if (offer.audience_type === "ACTIVE_USERS") {
    return "Active users";
  }
  if (offer.audience_type === "INACTIVE_USERS") {
    return "Inactive users";
  }
  return "All customers";
}

function formatGenerationReason(value: string | null): string {
  if (!value) {
    return "General campaign";
  }
  return value
    .replaceAll("_", " ")
    .toLowerCase()
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

function describeMatchTarget(match: GeneratedOfferUserMatch): string {
  if (match.target_type && match.target_id) {
    return `${match.target_type.toLowerCase()} · ${match.target_id}`;
  }
  if (match.target_type) {
    return match.target_type.toLowerCase();
  }
  return "Template-level match";
}

interface OffersSnapshot {
  restaurantContexts: RestaurantContext[];
  offers: OfferRow[];
}

export function OffersPage({
  token,
  role,
  restaurantId,
  onNavigate,
  onToast,
}: OffersPageProps) {
  // Remounted on every navigation to this page (see services/pageCache.ts),
  // so the key covers every input that changes what gets fetched: the
  // account (an admin sees every restaurant's offers) and, for an owner,
  // which restaurant.
  const offersKey = `offers:${tokenScope(token)}:${role === "ADMIN" ? "admin" : restaurantId ?? ""}`;
  const cachedOffers = getPageSnapshot<OffersSnapshot>(offersKey);
  const [restaurantContexts, setRestaurantContexts] = useState<RestaurantContext[]>(
    () => cachedOffers?.restaurantContexts ?? [],
  );
  const [offers, setOffers] = useState<OfferRow[]>(() => cachedOffers?.offers ?? []);
  // Only true when this account/restaurant has never been fetched this
  // session - not on every mount, so revisiting this page keeps showing its
  // data instead of a skeleton.
  const [loading, setLoading] = useState(() => !hasPageSnapshot(offersKey));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [stateFilter, setStateFilter] = useState<"ALL" | PersonalizedOfferState>("ALL");
  const [restaurantFilter, setRestaurantFilter] = useState<"ALL" | string>("ALL");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingOfferId, setEditingOfferId] = useState<string | null>(null);
  const [editingOfferKind, setEditingOfferKind] = useState<OfferEditorKind>("TEMPLATE");
  const [form, setForm] = useState<OfferFormState>(emptyOfferForm(restaurantId ?? ""));
  const [submitting, setSubmitting] = useState(false);
  const [offerPendingDelete, setOfferPendingDelete] = useState<OfferRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selectedOfferDetails, setSelectedOfferDetails] = useState<OfferRow | null>(null);
  const [generatedMatches, setGeneratedMatches] = useState<GeneratedOfferUserMatch[]>([]);
  const [generatedMatchesLoading, setGeneratedMatchesLoading] = useState(false);
  const [aiGenerationRunning, setAiGenerationRunning] = useState(false);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // `force`: bypasses the cache. The AI-generation flow below always forces,
  // since it exists specifically to fetch offers newer than whatever's
  // cached; the mount effect never does, which is what makes revisiting this
  // page free.
  const loadOffersWorkspace = useCallback(async (force = false) => {
    if (!force) {
      const cached = getPageSnapshot<OffersSnapshot>(offersKey);
      if (cached) {
        setRestaurantContexts(cached.restaurantContexts);
        setOffers(cached.offers);
        setLoading(false);
        return;
      }
    }

    setLoading(true);
    setLoadError(null);
    try {
      let restaurants: Restaurant[] = [];
      if (role === "ADMIN") {
        restaurants = await api.getAdminRestaurants(token);
      } else if (restaurantId) {
        const restaurant = await api.getRestaurant(token, restaurantId);
        restaurants = [restaurant];
      }

      const contexts = await Promise.all(
        restaurants.map(async (restaurant) => {
          const locations = await api.getRestaurantLocations(token, restaurant.id).catch(() => []);
          return {
            restaurant,
            locations,
          };
        }),
      );

      const offerRowsByRestaurant = await Promise.all(
        contexts.map(async ({ restaurant }) => {
          const rows = await api.getRestaurantOffers(token, restaurant.id);
          return rows.map<OfferRow>((offer) => ({
            ...offer,
            restaurant_name: restaurant.name,
            restaurant_slug: restaurant.slug,
            restaurant_city: restaurant.city,
          }));
        }),
      );

      if (!isMountedRef.current) {
        return;
      }
      const nextOffers = offerRowsByRestaurant.flat().sort((left, right) => {
        const expiryLeft = left.expires_at ? new Date(left.expires_at).getTime() : Number.MAX_SAFE_INTEGER;
        const expiryRight = right.expires_at ? new Date(right.expires_at).getTime() : Number.MAX_SAFE_INTEGER;
        return expiryLeft - expiryRight || left.name.localeCompare(right.name);
      });
      setRestaurantContexts(contexts);
      setOffers(nextOffers);
      setPageSnapshot<OffersSnapshot>(offersKey, {
        restaurantContexts: contexts,
        offers: nextOffers,
      });
    } catch (error: unknown) {
      if (!isMountedRef.current) {
        return;
      }
      onToast(
        "Offers unavailable",
        error instanceof ApiError ? error.message : "Unable to load offers right now.",
        "error",
      );
      setLoadError(
        error instanceof ApiError ? error.message : "Unable to load offers right now.",
      );
    } finally {
      if (isMountedRef.current) {
        setLoading(false);
      }
    }
  }, [offersKey, onToast, restaurantId, role, token]);

  useEffect(() => {
    void loadOffersWorkspace();
  }, [loadOffersWorkspace]);

  const restaurantContextsById = useMemo(
    () => Object.fromEntries(restaurantContexts.map((context) => [context.restaurant.id, context])),
    [restaurantContexts],
  );

  const activeRestaurantId =
    form.restaurant_id
    || restaurantContexts[0]?.restaurant.id
    || restaurantId
    || "";
  const activeRestaurantContext = activeRestaurantId ? restaurantContextsById[activeRestaurantId] : undefined;
  const availableLocations = activeRestaurantContext?.locations ?? [];
  const isEditingGeneratedOffer = editingOfferKind === "GENERATED";
  const filteredOffers = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return offers.filter((offer) => {
      if (stateFilter !== "ALL" && offer.effective_state !== stateFilter) {
        return false;
      }
      if (restaurantFilter !== "ALL" && offer.restaurant_id !== restaurantFilter) {
        return false;
      }
      if (!normalized) {
        return true;
      }
      return [
        offer.name,
        offer.restaurant_name,
        offer.offer_type,
        offer.restaurant_location_name ?? "",
      ].some((value) => value.toLowerCase().includes(normalized));
    });
  }, [offers, query, restaurantFilter, stateFilter]);

  const stateTiles = useMemo<Array<StatTileItem<"ALL" | PersonalizedOfferState>>>(() => {
    const countBy = (state: PersonalizedOfferState) =>
      offers.filter((offer) => offer.effective_state === state).length;
    return [
      { key: "ALL", label: "All offers", icon: TicketPercent, value: offers.length, hint: "Every campaign in scope" },
      { key: "ACTIVE", label: "Active", icon: PlayCircle, value: countBy("ACTIVE"), hint: "Live for customers" },
      { key: "DRAFT", label: "Draft", icon: FileEdit, value: countBy("DRAFT"), hint: "Not yet published" },
      { key: "PAUSED", label: "Paused", icon: PauseCircle, value: countBy("PAUSED"), hint: "Temporarily stopped" },
      { key: "EXPIRED", label: "Expired", icon: CalendarX2, value: countBy("EXPIRED"), hint: "Past their end date" },
      { key: "DISABLED", label: "Disabled", icon: Ban, value: countBy("DISABLED"), hint: "Turned off" },
    ];
  }, [offers]);

  const totalPages = Math.max(1, Math.ceil(filteredOffers.length / pageSize));
  const paginatedOffers = filteredOffers.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [pageSize, query, restaurantFilter, stateFilter]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  function formatDiscountSummary(offer: OfferRow): string {
    if (offer.discount_type === "NONE") {
      return "Info card";
    }
    if (offer.discount_type === "FREE_DELIVERY") {
      return "Free delivery";
    }
    if (offer.discount_type === "PERCENTAGE") {
      return `${offer.discount_value}% off`;
    }
    return `${formatCurrency(offer.discount_value)} off`;
  }

  function formatDiscountSupport(offer: OfferRow): string {
    if (offer.discount_type === "PERCENTAGE" && offer.max_discount_amount) {
      return `Up to ${formatCurrency(offer.max_discount_amount)}`;
    }
    if (offer.discount_type === "FREE_DELIVERY") {
      return offer.restaurant_location_name ?? "Eligible branches";
    }
    return offer.record_kind === "GENERATED"
      ? formatGenerationReason(offer.generation_reason)
      : formatOfferTypeLabel(offer.offer_type);
  }

  function formatValiditySummary(offer: OfferRow): string {
    if (offer.starts_at && offer.expires_at) {
      return `${formatDate(offer.starts_at)} - ${formatDate(offer.expires_at)}`;
    }
    if (offer.expires_at) {
      return `Ends ${formatDate(offer.expires_at)}`;
    }
    if (offer.starts_at) {
      return `Starts ${formatDate(offer.starts_at)}`;
    }
    return "No schedule";
  }

  const tableLoading = loading && !loadError && offers.length === 0;
  const tableEmptyState = useMemo(() => {
    if (restaurantContexts.length === 0) {
      return {
        title: "Nothing to manage yet",
        description: "No accessible restaurants were found for this account.",
      };
    }
    return {
      title: "No offers found",
      description:
        role === "ADMIN"
          ? "No manual or AI-generated offers are available yet. Try narrowing the filters."
          // The hint follows the button: generation is the owner's action now,
          // so the owner is the one told it exists.
          : "No offers are available for this restaurant yet. Try Generate AI Offers, or narrow the filters.",
    };
  }, [restaurantContexts.length, role]);

  const handleGenerateAiOffers = useCallback(async () => {
    // Owner-only. The platform-wide admin run still exists behind
    // /admin/offers/generate-ai, but generating offers is now something an
    // owner does for their own restaurant from their own screen.
    if (role !== "OWNER" || aiGenerationRunning) {
      return;
    }

    setAiGenerationRunning(true);
    try {
      const queued = await api.triggerOwnerAIOfferGeneration(token, {
        force_refresh: false,
      });
      let attempts = 0;

      while (attempts < 20) {
        attempts += 1;
        // The owner run executes inline, so the trigger response is already the
        // finished result. Polling it again would only add a wait to a job that
        // is done; the loop stays for the case where it comes back pending.
        const status =
          attempts === 1 && queued.ready
            ? queued
            : await (async () => {
                await new Promise((resolve) => window.setTimeout(resolve, 1500));
                return api.getOwnerAIOfferGenerationStatus(token, queued.task_id);
              })();
        if (!status.ready) {
          continue;
        }
        if (status.successful) {
          await loadOffersWorkspace(true);
          const generatedCount = status.summary?.offers_generated ?? 0;
          const matchedCount = status.summary?.customers_matched ?? 0;
          const scannedCount = status.summary?.users_scanned ?? 0;
          const consideredCount = status.summary?.segments_considered ?? 0;
          const alreadyRunning = status.summary?.segments_skipped ?? 0;
          if (!isMountedRef.current) {
            return;
          }
          if (generatedCount > 0) {
            onToast(
              "AI offers generated",
              // Offers and the customers they reach. The old wording counted
              // "users skipped", which meant something when the run wrote one
              // offer per customer and means nothing now that it writes a few
              // offers and matches people to them.
              `${generatedCount} offer${generatedCount === 1 ? "" : "s"} created from your order history` +
                (matchedCount > 0
                  ? `, reaching ${matchedCount} of ${scannedCount} customers.`
                  : "."),
              "success",
            );
          } else if (alreadyRunning > 0) {
            onToast(
              "Your offers are already up to date",
              `Every pattern we found (${alreadyRunning}) is already covered by a live offer, so nothing was duplicated.`,
              "info",
            );
          } else {
            onToast(
              "No new AI offers generated",
              consideredCount === 0 && scannedCount === 0
                ? "There is not enough order history yet to find a pattern worth an offer."
                : "No pattern was strong enough to build an offer from. More orders will change that.",
              "info",
            );
          }
        } else {
          if (!isMountedRef.current) {
            return;
          }
          onToast(
            "AI offer generation failed",
            status.error ?? "The AI offer task did not complete successfully.",
            "error",
          );
        }
        setAiGenerationRunning(false);
        return;
      }

      if (!isMountedRef.current) {
        return;
      }
      onToast(
        "AI offer generation is still pending",
        "The task did not finish in time. Check that the Celery worker is running, then refresh the Offers screen.",
        "error",
      );
    } catch (error: unknown) {
      if (!isMountedRef.current) {
        return;
      }
      onToast(
        "Unable to generate AI offers",
        error instanceof ApiError ? error.message : "The AI generation task could not be started.",
        "error",
      );
    } finally {
      if (isMountedRef.current) {
        setAiGenerationRunning(false);
      }
    }
  }, [aiGenerationRunning, loadOffersWorkspace, onToast, role, token]);

  const columns: Array<TableColumn<OfferRow>> = [
    {
      id: "offer",
      header: "Offer title",
      render: (offer) => (
        <div className="offer-table__title">
          <strong>{offer.name}</strong>
          <span className="offer-table__meta">
            {offer.record_kind === "GENERATED"
              ? offer.manually_edited
                ? "AI generated • Manually edited"
                : "AI generated"
              : offer.generated_title
                ? "Generated copy active"
                : "Template ready"}
          </span>
        </div>
      ),
      mobileLabel: "Offer",
    },
    {
      id: "source",
      header: "Source",
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{offer.record_kind === "GENERATED" ? "AI generated" : "Manual"}</strong>
          <span>{formatOfferTypeLabel(offer.offer_type)}</span>
        </div>
      ),
      mobileLabel: "Source",
    },
    {
      id: "restaurant",
      header: "Restaurant",
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{offer.restaurant_name}</strong>
          <span>{offer.restaurant_location_name ?? offer.restaurant_city}</span>
        </div>
      ),
      hideOnMobile: true,
    },
    {
      id: "scope",
      header: "Scope",
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{describeOfferScope(offer)}</strong>
          <span>{offer.restaurant_location_name ?? "All branches"}</span>
        </div>
      ),
      mobileLabel: "Scope",
    },
    {
      id: "discount",
      header: "Discount",
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{formatDiscountSummary(offer)}</strong>
          <span>{formatDiscountSupport(offer)}</span>
        </div>
      ),
      mobileLabel: "Discount",
      align: "right",
    },
    {
      id: "minimum-order",
      header: "Min order",
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{formatCurrency(offer.minimum_order_amount)}</strong>
          <span>{describeOfferSegment(offer)}</span>
        </div>
      ),
      mobileLabel: "Min order",
      align: "right",
    },
    {
      id: "status",
      header: "Status",
      render: (offer) => (
        <div className="offer-table__status">
          <StatusPill status={offer.effective_state} />
          <span>
            {offer.record_kind === "GENERATED"
              ? `${offer.eligible_user_count} matched users`
              : offer.state === offer.effective_state
                ? "Live as configured"
                : `Saved as ${offer.state.toLowerCase()}`}
          </span>
        </div>
      ),
      mobileLabel: "Status",
    },
    {
      id: "dates",
      header: "End date",
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{offer.expires_at ? formatDate(offer.expires_at) : "No expiry"}</strong>
          <span>{offer.starts_at ? `Starts ${formatDate(offer.starts_at)}` : `Created ${formatDate(offer.created_at)}`}</span>
        </div>
      ),
      mobileLabel: "Dates",
    },
  ];

  const openCreateModal = async () => {
    const nextRestaurantId = role === "OWNER"
      ? (restaurantId ?? restaurantContexts[0]?.restaurant.id ?? "")
      : (restaurantFilter !== "ALL" ? restaurantFilter : (restaurantContexts[0]?.restaurant.id ?? ""));
    setEditingOfferId(null);
    setEditingOfferKind("TEMPLATE");
    setForm(emptyOfferForm(nextRestaurantId));
    setIsModalOpen(true);
  };

  const openEditModal = async (offer: OfferRow) => {
    setEditingOfferId(offer.id);
    setEditingOfferKind(offer.record_kind);
    setForm(fromOffer(offer));
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setEditingOfferId(null);
    setEditingOfferKind("TEMPLATE");
    setForm(emptyOfferForm(role === "OWNER" ? (restaurantId ?? "") : ""));
    setIsModalOpen(false);
    setSubmitting(false);
  };

  const closeOfferDetails = () => {
    setSelectedOfferDetails(null);
    setGeneratedMatches([]);
    setGeneratedMatchesLoading(false);
  };

  const openOfferDetails = async (offer: OfferRow) => {
    setSelectedOfferDetails(offer);
    setGeneratedMatches([]);
    if (offer.record_kind !== "GENERATED") {
      setGeneratedMatchesLoading(false);
      return;
    }
    setGeneratedMatchesLoading(true);
    try {
      const matches = await api.getGeneratedOfferMatches(token, offer.restaurant_id, offer.id);
      setGeneratedMatches(matches);
    } catch (error: unknown) {
      onToast(
        "Generated matches unavailable",
        error instanceof ApiError ? error.message : "Unable to load matched users right now.",
        "error",
      );
      setSelectedOfferDetails(null);
    } finally {
      setGeneratedMatchesLoading(false);
    }
  };

  const upsertOffer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) {
      return;
    }
    if (!form.restaurant_id) {
      onToast("Restaurant required", "Choose a restaurant before saving this offer.", "error");
      return;
    }

    setSubmitting(true);
    try {
      const payload = buildPayload(form);
      const editingOffer = editingOfferId
        ? offers.find((offer) => offer.id === editingOfferId) ?? null
        : null;
      const saved = editingOfferId
        ? editingOfferKind === "GENERATED" && editingOffer
          ? await api.updateGeneratedOfferState(
              token,
              form.restaurant_id,
              editingOfferId,
              buildGeneratedOfferPayload(form, editingOffer),
            )
          : await api.updateRestaurantOffer(token, form.restaurant_id, editingOfferId, payload)
        : await api.createRestaurantOffer(token, form.restaurant_id, payload);
      const restaurant = restaurantContextsById[form.restaurant_id]?.restaurant;
      const nextRow: OfferRow = {
        ...saved,
        restaurant_name: restaurant?.name ?? "Unknown restaurant",
        restaurant_slug: restaurant?.slug ?? "",
        restaurant_city: restaurant?.city ?? "",
      };
      setOffers((current) => {
        const next = !editingOfferId
          ? [nextRow, ...current]
          : current.map((offer) => (offer.id === nextRow.id ? nextRow : offer));
        // Genuine data change: keeps the cache in step with what's now on
        // screen.
        setPageSnapshot<OffersSnapshot>(offersKey, { restaurantContexts, offers: next });
        return next;
      });
      closeModal();
      onToast(
        editingOfferId ? "Offer updated" : "Offer created",
        editingOfferKind === "GENERATED"
          ? `${saved.name} was updated for customer-facing surfaces.`
          : `${saved.name} is ready for generation and customer matching.`,
        "success",
      );
    } catch (error: unknown) {
      setSubmitting(false);
      onToast(
        "Offer save failed",
        error instanceof ApiError ? error.message : "Unable to save this offer right now.",
        "error",
      );
    }
  };

  const updateOfferState = async (
    offer: OfferRow,
    nextState: PersonalizedOfferState,
    successMessage: string,
  ) => {
    try {
      const updated = offer.record_kind === "GENERATED"
        ? await api.updateGeneratedOfferState(token, offer.restaurant_id, offer.id, { state: nextState })
        : await api.updateRestaurantOffer(
            token,
            offer.restaurant_id,
            offer.id,
            buildQuickTogglePayload(offer, nextState),
          );
      const nextRow: OfferRow = {
        ...updated,
        restaurant_name: offer.restaurant_name,
        restaurant_slug: offer.restaurant_slug,
        restaurant_city: offer.restaurant_city,
      };
      setOffers((current) => {
        const next = current.map((row) => (row.id === nextRow.id ? nextRow : row));
        setPageSnapshot<OffersSnapshot>(offersKey, { restaurantContexts, offers: next });
        return next;
      });
      onToast("Offer updated", successMessage.replace("{name}", updated.name), "success");
    } catch (error: unknown) {
      onToast(
        "Offer update failed",
        error instanceof ApiError ? error.message : "Unable to change this offer state right now.",
        "error",
      );
    }
  };

  const confirmDeleteOffer = async () => {
    if (!offerPendingDelete || deleting) {
      return;
    }
    setDeleting(true);
    try {
      if (offerPendingDelete.record_kind === "GENERATED") {
        await api.deleteGeneratedOffer(token, offerPendingDelete.restaurant_id, offerPendingDelete.id);
      } else {
        await api.deleteRestaurantOffer(token, offerPendingDelete.restaurant_id, offerPendingDelete.id);
      }
      setOffers((current) => {
        const next = current.filter((offer) => offer.id !== offerPendingDelete.id);
        setPageSnapshot<OffersSnapshot>(offersKey, { restaurantContexts, offers: next });
        return next;
      });
      onToast("Offer deleted", `${offerPendingDelete.name} was deleted.`, "success");
      setOfferPendingDelete(null);
    } catch (error: unknown) {
      onToast(
        "Offer delete failed",
        error instanceof ApiError ? error.message : "Unable to delete this offer right now.",
        "error",
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Campaign control"
        title="Offers"
        description={
          role === "ADMIN"
            ? "Manage manual restaurant and branch campaigns across the platform."
            : "Manage reusable templates and AI-generated campaigns for your restaurant."
        }
        actions={
          <>
            {role === "ADMIN" ? (
              <button
                className="secondary-button"
                onClick={() => onNavigate("/restaurants")}
                type="button"
              >
                <Store size={16} strokeWidth={2.2} />
                Restaurants
              </button>
            ) : null}
            {/* Generation moved here from the admin panel: it reads this
                restaurant's own order history, so it belongs to the person who
                owns that data rather than to a platform-wide sweep. */}
            {role === "OWNER" ? (
              <button
                className="secondary-button"
                disabled={aiGenerationRunning}
                onClick={() => void handleGenerateAiOffers()}
                type="button"
              >
                <PlayCircle size={16} strokeWidth={2.2} />
                {aiGenerationRunning ? "Generating AI offers…" : "Generate AI Offers"}
              </button>
            ) : null}
            <button className="primary-button" onClick={() => void openCreateModal()} type="button">
              <TicketPercent size={16} strokeWidth={2.2} />
              Create offer
            </button>
          </>
        }
      />

      <StatTiles<"ALL" | PersonalizedOfferState>
        active={stateFilter}
        ariaLabel="Offer state distribution"
        loading={tableLoading}
        onSelect={setStateFilter}
        tiles={stateTiles}
      />

      <section className="admin-surface">
        <DataToolbar
          actions={<span className="toolbar-meta">{pluralize(filteredOffers.length, "offer")}</span>}
          filters={
            <>
              {role === "ADMIN" ? (
                <select
                  className="page-search page-search--select"
                  onChange={(event) => setRestaurantFilter(event.target.value as typeof restaurantFilter)}
                  value={restaurantFilter}
                >
                  <option value="ALL">All restaurants</option>
                  {restaurantContexts.map((context) => (
                    <option key={context.restaurant.id} value={context.restaurant.id}>
                      {context.restaurant.name}
                    </option>
                  ))}
                </select>
              ) : null}
              <select
                className="page-search page-search--select"
                onChange={(event) => setStateFilter(event.target.value as typeof stateFilter)}
                value={stateFilter}
              >
                <option value="ALL">All states</option>
                <option value="DRAFT">Draft</option>
                <option value="ACTIVE">Active</option>
                <option value="PAUSED">Paused</option>
                <option value="EXPIRED">Expired</option>
                <option value="DISABLED">Disabled</option>
              </select>
            </>
          }
          onSearchChange={setQuery}
          searchPlaceholder="Search by offer, restaurant, scope..."
          searchValue={query}
        />

        <ResponsiveTable
          actions={[
            {
              id: "view",
              label: "View",
              icon: Eye,
              onClick: (offer) => void openOfferDetails(offer),
            },
            {
              id: "edit",
              label: "Edit",
              icon: Edit3,
              onClick: (offer) => void openEditModal(offer),
              hidden: (offer) => !offer.editable,
            },
            {
              id: "enable",
              label: "Enable",
              icon: PlayCircle,
              onClick: (offer) =>
                void updateOfferState(offer, "ACTIVE", "{name} is now active."),
              hidden: (offer) => offer.effective_state === "ACTIVE" || offer.effective_state === "EXPIRED",
              tone: "success",
            },
            {
              id: "disable",
              label: "Disable",
              icon: Ban,
              onClick: (offer) =>
                void updateOfferState(offer, "DISABLED", "{name} is now disabled."),
              hidden: (offer) => offer.state === "DISABLED" || offer.effective_state === "EXPIRED",
            },
            {
              id: "delete",
              label: "Delete",
              icon: Trash2,
              onClick: (offer) => setOfferPendingDelete(offer),
              tone: "danger",
            },
          ]}
          columns={columns}
          emptyAction={
            <button
              className="primary-button"
              onClick={() => void openCreateModal()}
              type="button"
            >
              <TicketPercent size={15} strokeWidth={2.1} />
              Create offer
            </button>
          }
          emptyDescription={tableEmptyState.description}
          emptyTitle={tableEmptyState.title}
          error={loadError}
          keyExtractor={(offer) => offer.id}
          onRetry={() => {
            setLoadError(null);
            void loadOffersWorkspace(true);
          }}
          loading={tableLoading}
          mobileStatus={(offer) => <StatusPill status={offer.effective_state} />}
          mobileSubtitle={(offer) => `${offer.record_kind === "GENERATED" ? "AI generated" : "Manual template"} · ${offer.restaurant_name}`}
          mobileTitle={(offer) => offer.name}
          onRowClick={(offer) => {
            void openOfferDetails(offer);
          }}
          rows={paginatedOffers}
        />

        <Pagination
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          page={page}
          pageSize={pageSize}
          totalItems={filteredOffers.length}
          totalPages={totalPages}
        />
      </section>

      <ConfirmDialog
        open={offerPendingDelete !== null}
        eyebrow="Delete offer"
        title="Are you sure you want to delete this offer?"
        description={
          offerPendingDelete
            ? `${offerPendingDelete.name} will be removed from customer surfaces and will stop applying immediately.`
            : ""
        }
        confirmLabel="Delete offer"
        busy={deleting}
        onCancel={() => {
          if (deleting) {
            return;
          }
          setOfferPendingDelete(null);
        }}
        onConfirm={() => void confirmDeleteOffer()}
        tone="danger"
      />

      {selectedOfferDetails ? (
        <Modal onClose={closeOfferDetails} className="combo-detail-modal">
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">
                  {selectedOfferDetails.record_kind === "GENERATED" ? "Generated campaign" : "Offer details"}
                </span>
                <h2>{selectedOfferDetails.generated_title ?? selectedOfferDetails.name}</h2>
                <p className="hint-text">
                  {selectedOfferDetails.generated_subtitle
                    ?? (selectedOfferDetails.record_kind === "GENERATED"
                      ? "This campaign was generated from a reusable offer template."
                      : "This manual template controls discount rules, scope, and validity for matching customers.")}
                </p>
              </div>
              <button
                aria-label="Close offer details"
                className="modal-close"
                onClick={closeOfferDetails}
                type="button"
              >
                ×
              </button>
            </div>

            <div className="modal-card__body combo-detail-modal__body">
              <div className="detail-grid">
                <div>
                  <strong>Source</strong>
                  <span>
                    {selectedOfferDetails.record_kind === "GENERATED"
                      ? selectedOfferDetails.manually_edited
                        ? "AI generated campaign • Manually edited"
                        : "AI generated campaign"
                      : "Manual template"}
                  </span>
                </div>
                <div>
                  <strong>Offer type</strong>
                  <span>{formatOfferTypeLabel(selectedOfferDetails.offer_type)}</span>
                </div>
                <div>
                  <strong>Restaurant scope</strong>
                  <span>{selectedOfferDetails.restaurant_name} · {selectedOfferDetails.restaurant_location_name ?? "All branches"}</span>
                </div>
                <div>
                  <strong>Target scope</strong>
                  <span>{describeOfferScope(selectedOfferDetails)}</span>
                </div>
                <div>
                  <strong>Discount</strong>
                  <span>{formatDiscountSummary(selectedOfferDetails)} · Min {formatCurrency(selectedOfferDetails.minimum_order_amount)}</span>
                </div>
                <div>
                  <strong>Performance</strong>
                  <span>{selectedOfferDetails.view_count} views · {selectedOfferDetails.click_count} clicks · {selectedOfferDetails.conversion_count} conversions</span>
                </div>
                <div>
                  <strong>Status</strong>
                  <span>{selectedOfferDetails.effective_state.toLowerCase()}</span>
                </div>
                {selectedOfferDetails.record_kind === "GENERATED" && selectedOfferDetails.manually_edited ? (
                  <div>
                    <strong>Edited by</strong>
                    <span>
                      {selectedOfferDetails.edited_by ?? "Unknown"}
                      {selectedOfferDetails.edited_at ? ` · ${formatDate(selectedOfferDetails.edited_at)}` : ""}
                    </span>
                  </div>
                ) : null}
                <div>
                  <strong>Validity</strong>
                  <span>{formatValiditySummary(selectedOfferDetails)}</span>
                </div>
              </div>

              {selectedOfferDetails.record_kind === "GENERATED" ? (
                <div className="combo-detail-section">
                  <strong>Matched users</strong>
                  {generatedMatchesLoading ? (
                    <span className="hint-text">Loading matched users...</span>
                  ) : generatedMatches.length === 0 ? (
                    <span className="hint-text">No users have been matched to this generated campaign yet.</span>
                  ) : (
                    <div className="combo-detail-items">
                      {generatedMatches.map((match) => (
                        <div className="combo-detail-item" key={match.id}>
                          <div>
                            <strong>{match.user_name}</strong>
                            <span>{match.user_email}</span>
                            <span>{formatGenerationReason(match.matched_reason)}</span>
                          </div>
                          <div className="combo-detail-item__meta">
                            <strong>Rank #{match.rank}</strong>
                            <span>Score {Number(match.score).toFixed(2)}</span>
                            <span>{describeMatchTarget(match)}</span>
                            <span>{match.view_count} views · {match.click_count} clicks · {match.conversion_count} conversions</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ) : (
                <div className="combo-detail-section">
                  <strong>Template usage</strong>
                  <span className="hint-text">
                    Generated user matches and surfacing analytics appear here automatically once this template is used to generate live campaigns.
                  </span>
                </div>
              )}
            </div>
          </Modal>
      ) : null}

      {isModalOpen ? (
        <Modal onClose={closeModal}>
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Campaign editor</span>
                <h2>{editingOfferId ? (isEditingGeneratedOffer ? "Edit AI offer" : "Edit offer") : "Create offer"}</h2>
                <p className="hint-text">
                  {isEditingGeneratedOffer
                    ? "Fine-tune AI-generated customer copy and availability timing. Discount logic and checkout validation remain backend-controlled."
                    : "Set discount rules, spend threshold, branch scope, and validity for this manual campaign."}
                </p>
              </div>
              <button
                aria-label="Close offer form"
                className="modal-close"
                onClick={closeModal}
                type="button"
              >
                ×
              </button>
            </div>

            <form className="form-grid modal-card__body" onSubmit={upsertOffer}>
              {role === "ADMIN" && !isEditingGeneratedOffer ? (
                <label className="field form-grid__wide">
                  <span>Restaurant</span>
                  <select
                    required
                    value={form.restaurant_id}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        restaurant_id: event.target.value,
                        restaurant_location_id: "",
                        applicable_item_id: "",
                      }))
                    }
                  >
                    <option value="">Select restaurant</option>
                    {restaurantContexts.map((context) => (
                      <option key={context.restaurant.id} value={context.restaurant.id}>
                        {context.restaurant.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <label className="field form-grid__wide">
                <span>{isEditingGeneratedOffer ? "Card title" : "Offer title"}</span>
                <input
                  required
                  value={form.name}
                  onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
              {isEditingGeneratedOffer ? (
                <>
                  <label className="field form-grid__wide">
                    <span>Card subtitle</span>
                    <textarea
                      rows={3}
                      value={form.generated_subtitle}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, generated_subtitle: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Badge</span>
                    <input
                      placeholder="Optional"
                      value={form.generated_badge}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, generated_badge: event.target.value }))
                      }
                    />
                  </label>
                </>
              ) : null}
              {!isEditingGeneratedOffer ? (
                <>
                  <label className="field">
                    <span>Offer type</span>
                    <select
                      value={form.offer_type}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          offer_type: event.target.value as PersonalizedOfferType,
                        }))
                      }
                    >
                      {OFFER_TYPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Audience</span>
                    <select
                      value={form.audience_type}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          audience_type: event.target.value as PersonalizedOfferAudience,
                        }))
                      }
                    >
                      {AUDIENCE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              ) : (
                <div className="field">
                  <span>Offer type</span>
                  <input disabled value={formatOfferTypeLabel(form.offer_type)} />
                </div>
              )}
              <label className="field">
                <span>Status</span>
                <select
                  value={form.state}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      state: event.target.value as PersonalizedOfferState,
                    }))
                  }
                >
                  {OFFER_STATE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
              {!isEditingGeneratedOffer ? (
                <>
                  <label className="field">
                    <span>Branch scope</span>
                    <select
                      value={form.restaurant_location_id}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          restaurant_location_id: event.target.value,
                        }))
                      }
                    >
                      <option value="">All branches</option>
                      {availableLocations.map((location) => (
                        <option key={location.id} value={location.id}>
                          {location.branch_name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Category scope</span>
                    <input
                      placeholder="Optional, e.g. Pizza"
                      value={form.applicable_category}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, applicable_category: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Cuisine scope</span>
                    <input
                      placeholder="Optional, e.g. Thai"
                      value={form.applicable_cuisine}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, applicable_cuisine: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Discount type</span>
                    <select
                      value={form.discount_type}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          discount_type: event.target.value as PersonalizedOfferDiscountType,
                        }))
                      }
                    >
                      {DISCOUNT_TYPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Discount value</span>
                    <input
                      min="0"
                      step="0.01"
                      type="number"
                      disabled={form.discount_type === "NONE" || form.discount_type === "FREE_DELIVERY"}
                      value={form.discount_value}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, discount_value: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Max discount</span>
                    <input
                      min="0"
                      placeholder="Optional"
                      step="0.01"
                      type="number"
                      disabled={form.discount_type !== "PERCENTAGE"}
                      value={form.max_discount_amount}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, max_discount_amount: event.target.value }))
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Minimum order</span>
                    <input
                      min="0"
                      step="0.01"
                      type="number"
                      value={form.minimum_order_amount}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, minimum_order_amount: event.target.value }))
                      }
                    />
                  </label>
                </>
              ) : (
                <div className="field form-grid__wide">
                  <span>Offer rules</span>
                  <div className="hint-text">
                    Discount type, discount value, scope, and checkout validation remain backend-controlled for AI-generated offers.
                  </div>
                </div>
              )}
              <label className="field">
                <span>CTA label</span>
                <input
                  placeholder="Optional"
                  value={form.cta_label}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, cta_label: event.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>Starts at</span>
                <input
                  type="datetime-local"
                  value={form.starts_at}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, starts_at: event.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>Expires at</span>
                <input
                  type="datetime-local"
                  value={form.expires_at}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, expires_at: event.target.value }))
                  }
                />
              </label>
              {isEditingGeneratedOffer ? (
                <div className="field form-grid__wide">
                  <span>Override status</span>
                  <div className="hint-text">
                    Original AI provenance is preserved. This edit will be tracked as a manual override in generated-offer metadata.
                  </div>
                </div>
              ) : (
                <label className="field form-grid__wide">
                  <span>Description</span>
                  <textarea
                    rows={4}
                    placeholder="Short customer-facing description shown on the offer card"
                    value={form.notes}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, notes: event.target.value }))
                    }
                  />
                </label>
              )}

              <div className="modal-card__footer form-grid__wide">
                <button className="secondary-button" onClick={closeModal} type="button">
                  Cancel
                </button>
                <button className="primary-button" disabled={submitting} type="submit">
                  {submitting ? "Saving..." : editingOfferId ? "Save changes" : "Create offer"}
                </button>
              </div>
            </form>
          </Modal>
      ) : null}
    </div>
  );
}
