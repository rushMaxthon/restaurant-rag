import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Ban, Edit3, Eye, PlayCircle, Trash2 } from 'lucide-react';
import { ConfirmDialog } from './ConfirmDialog';
import { DataToolbar } from './DataToolbar';
import { EmptyPanel } from './EmptyPanel';
import { Pagination } from './Pagination';
import { ResponsiveTable, type TableColumn } from './ResponsiveTable';
import { Modal } from './Modal';
import { StatusPill } from './StatusPill';
import { ApiError, api, formatCurrency, formatDate } from '../services/api';
import type {
  GeneratedOfferUserMatch,
  ManagedPersonalizedOffer,
  PersonalizedOfferAudience,
  PersonalizedOfferDiscountType,
  PersonalizedOfferState,
  PersonalizedOfferType,
  RestaurantDetail,
} from '../types/app';

interface RestaurantOffersManagerProps {
  token: string;
  restaurant: RestaurantDetail;
  onToast: (
    title: string,
    description: string,
    tone?: 'success' | 'error' | 'info',
  ) => void;
}

type OfferFormState = {
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

type OfferEditorKind = 'TEMPLATE' | 'GENERATED';

const OFFER_TYPE_OPTIONS: Array<{ value: PersonalizedOfferType; label: string }> = [
  { value: 'FAVORITE_RESTAURANT', label: 'Favorite restaurant' },
  { value: 'FAVORITE_ITEM', label: 'Repeated item' },
  { value: 'ORDER_HISTORY_MATCH', label: 'Order history match' },
  { value: 'CUISINE_AFFINITY', label: 'Cuisine affinity' },
  { value: 'PREFERENCE_MATCH', label: 'Preference match' },
  { value: 'TASTE_MATCH', label: 'Taste match' },
  { value: 'COMBO_AFFINITY', label: 'Combo affinity' },
  { value: 'BUDGET_BEHAVIOR', label: 'Budget behavior' },
  { value: 'NEW_ITEM_MATCH', label: 'New item match' },
  { value: 'WELCOME_FIRST_ORDER', label: 'First-order welcome' },
  { value: 'CUSTOM', label: 'Custom' },
];

const AUDIENCE_OPTIONS: Array<{ value: PersonalizedOfferAudience; label: string }> = [
  { value: 'ALL_CUSTOMERS', label: 'All customers' },
  { value: 'ACTIVE_USERS', label: 'Active users' },
  { value: 'INACTIVE_USERS', label: 'Inactive users' },
];

const OFFER_STATE_OPTIONS: Array<{ value: PersonalizedOfferState; label: string }> = [
  { value: 'DRAFT', label: 'Draft' },
  { value: 'ACTIVE', label: 'Active' },
  { value: 'PAUSED', label: 'Paused' },
  { value: 'DISABLED', label: 'Disabled' },
];

const DISCOUNT_TYPE_OPTIONS: Array<{ value: PersonalizedOfferDiscountType; label: string }> = [
  { value: 'NONE', label: 'No discount / info card' },
  { value: 'PERCENTAGE', label: 'Percentage' },
  { value: 'FLAT', label: 'Flat amount' },
  { value: 'FREE_DELIVERY', label: 'Free delivery' },
];

function emptyOfferForm(): OfferFormState {
  return {
    name: '',
    generated_subtitle: '',
    generated_badge: '',
    offer_type: 'FAVORITE_RESTAURANT',
    audience_type: 'ALL_CUSTOMERS',
    state: 'DRAFT',
    restaurant_location_id: '',
    applicable_category: '',
    applicable_cuisine: '',
    discount_type: 'NONE',
    discount_value: '0',
    max_discount_amount: '',
    minimum_order_amount: '0',
    cta_label: '',
    starts_at: '',
    expires_at: '',
    notes: '',
  };
}

function toDateTimeLocal(value: string | null): string {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
}

function fromOffer(offer: ManagedPersonalizedOffer): OfferFormState {
  return {
    name: offer.record_kind === 'GENERATED' ? (offer.generated_title ?? offer.name) : offer.name,
    generated_subtitle: offer.generated_subtitle ?? '',
    generated_badge: offer.generated_badge ?? '',
    offer_type: offer.offer_type,
    audience_type: offer.audience_type,
    state: offer.state,
    restaurant_location_id: offer.restaurant_location_id ?? '',
    applicable_category: offer.applicable_category ?? '',
    applicable_cuisine: offer.applicable_cuisine ?? '',
    discount_type: offer.discount_type,
    discount_value: String(offer.discount_value ?? 0),
    max_discount_amount: offer.max_discount_amount == null ? '' : String(offer.max_discount_amount),
    minimum_order_amount: String(offer.minimum_order_amount ?? 0),
    cta_label: offer.record_kind === 'GENERATED' ? (offer.generated_cta_label ?? offer.cta_label ?? '') : (offer.cta_label ?? ''),
    starts_at: toDateTimeLocal(offer.starts_at),
    expires_at: toDateTimeLocal(offer.expires_at),
    notes: offer.notes ?? '',
  };
}

function buildGeneratedOfferPayload(form: OfferFormState, offer: ManagedPersonalizedOffer) {
  return {
    state: form.state,
    title: form.name.trim() || offer.generated_title || offer.name,
    subtitle: form.generated_subtitle.trim() || offer.generated_subtitle || '',
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
  offer: ManagedPersonalizedOffer,
  nextState: PersonalizedOfferState,
) {
  return {
    ...buildPayload(fromOffer(offer)),
    state: nextState,
  };
}

function formatOfferTypeLabel(value: PersonalizedOfferType): string {
  const option = OFFER_TYPE_OPTIONS.find(entry => entry.value === value);
  return option?.label ?? value;
}

function describeOfferScope(offer: ManagedPersonalizedOffer): string {
  return (
    offer.applicable_item_name
    ?? offer.applicable_category
    ?? offer.applicable_cuisine
    ?? 'Restaurant wide'
  );
}

function describeOfferSegment(offer: ManagedPersonalizedOffer): string {
  if (offer.offer_type === 'WELCOME_FIRST_ORDER') {
    return 'First order only';
  }
  if (offer.audience_type === 'ACTIVE_USERS') {
    return 'Active users';
  }
  if (offer.audience_type === 'INACTIVE_USERS') {
    return 'Inactive users';
  }
  return 'All customers';
}

function formatGenerationReason(value: string | null): string {
  if (!value) {
    return 'General campaign';
  }
  return value
    .replaceAll('_', ' ')
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
  return 'Template-level match';
}

export function RestaurantOffersManager({
  token,
  restaurant,
  onToast,
}: RestaurantOffersManagerProps) {
  const [offers, setOffers] = useState<ManagedPersonalizedOffer[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [stateFilter, setStateFilter] = useState<'ALL' | PersonalizedOfferState>('ALL');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingOfferId, setEditingOfferId] = useState<string | null>(null);
  const [editingOfferKind, setEditingOfferKind] = useState<OfferEditorKind>('TEMPLATE');
  const [form, setForm] = useState<OfferFormState>(emptyOfferForm());
  const [submitting, setSubmitting] = useState(false);
  const [offerPendingDelete, setOfferPendingDelete] = useState<ManagedPersonalizedOffer | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selectedOfferDetails, setSelectedOfferDetails] = useState<ManagedPersonalizedOffer | null>(null);
  const [generatedMatches, setGeneratedMatches] = useState<GeneratedOfferUserMatch[]>([]);
  const [generatedMatchesLoading, setGeneratedMatchesLoading] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError(null);

    Promise.all([
      api.getRestaurantOffers(token, restaurant.id),
    ])
      .then(([offerRows]) => {
        if (!active) {
          return;
        }
        setOffers(offerRows);
        setLoading(false);
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        setLoading(false);
        onToast(
          'Offers unavailable',
          error instanceof ApiError ? error.message : 'Unable to load restaurant offers right now.',
          'error',
        );
        setLoadError(
          error instanceof ApiError ? error.message : 'Unable to load restaurant offers right now.',
        );
      });

    return () => {
      active = false;
    };
  }, [onToast, restaurant.id, token]);

  const filteredOffers = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return offers.filter((offer) => {
      if (stateFilter !== 'ALL' && offer.effective_state !== stateFilter) {
        return false;
      }
      if (!normalized) {
        return true;
      }
      return [
        offer.name,
        offer.offer_type,
        offer.restaurant_location_name ?? '',
      ].some((value) => value.toLowerCase().includes(normalized));
    });
  }, [offers, query, stateFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredOffers.length / pageSize));
  const paginatedOffers = filteredOffers.slice((page - 1) * pageSize, page * pageSize);
  const isEditingGeneratedOffer = editingOfferKind === 'GENERATED';

  useEffect(() => {
    setPage(1);
  }, [pageSize, query, stateFilter]);

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [page, totalPages]);

  function formatDiscountSummary(offer: ManagedPersonalizedOffer): string {
    if (offer.discount_type === 'NONE') {
      return 'Info card';
    }
    if (offer.discount_type === 'FREE_DELIVERY') {
      return 'Free delivery';
    }
    if (offer.discount_type === 'PERCENTAGE') {
      return `${offer.discount_value}% off`;
    }
    return `${formatCurrency(offer.discount_value)} off`;
  }

  function formatDiscountSupport(offer: ManagedPersonalizedOffer): string {
    if (offer.discount_type === 'PERCENTAGE' && offer.max_discount_amount) {
      return `Up to ${formatCurrency(offer.max_discount_amount)}`;
    }
    if (offer.discount_type === 'FREE_DELIVERY') {
      return offer.restaurant_location_name ?? 'Eligible branches';
    }
    return offer.record_kind === 'GENERATED'
      ? formatGenerationReason(offer.generation_reason)
      : formatOfferTypeLabel(offer.offer_type);
  }

  function formatValiditySummary(offer: ManagedPersonalizedOffer): string {
    if (offer.starts_at && offer.expires_at) {
      return `${formatDate(offer.starts_at)} - ${formatDate(offer.expires_at)}`;
    }
    if (offer.expires_at) {
      return `Ends ${formatDate(offer.expires_at)}`;
    }
    if (offer.starts_at) {
      return `Starts ${formatDate(offer.starts_at)}`;
    }
    return 'No schedule';
  }

  const columns: Array<TableColumn<ManagedPersonalizedOffer>> = [
    {
      id: 'offer',
      header: 'Offer title',
      render: (offer) => (
        <div className="offer-table__title">
          <strong>{offer.name}</strong>
          <span className="offer-table__meta">
            {offer.record_kind === 'GENERATED'
              ? offer.manually_edited
                ? 'AI generated • Manually edited'
                : 'AI generated'
              : offer.generated_title
                ? 'Generated copy active'
                : 'Template ready'}
          </span>
        </div>
      ),
      mobileLabel: 'Offer',
    },
    {
      id: 'source',
      header: 'Source',
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{offer.record_kind === 'GENERATED' ? 'AI generated' : 'Manual'}</strong>
          <span>{formatOfferTypeLabel(offer.offer_type)}</span>
        </div>
      ),
      mobileLabel: 'Source',
    },
    {
      id: 'scope',
      header: 'Scope',
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{describeOfferScope(offer)}</strong>
          <span>{offer.restaurant_location_name ?? 'All branches'}</span>
        </div>
      ),
      mobileLabel: 'Scope',
    },
    {
      id: 'discount',
      header: 'Discount',
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{formatDiscountSummary(offer)}</strong>
          <span>{formatDiscountSupport(offer)}</span>
        </div>
      ),
      mobileLabel: 'Discount',
      align: 'right',
    },
    {
      id: 'minimum-order',
      header: 'Min order',
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{formatCurrency(offer.minimum_order_amount)}</strong>
          <span>{describeOfferSegment(offer)}</span>
        </div>
      ),
      mobileLabel: 'Min order',
      align: 'right',
    },
    {
      id: 'status',
      header: 'Status',
      render: (offer) => (
        <div className="offer-table__status">
          <StatusPill status={offer.effective_state} />
          <span>{offer.record_kind === 'GENERATED' ? `${offer.eligible_user_count} matched users` : (offer.state === offer.effective_state ? 'Live as configured' : `Saved as ${offer.state.toLowerCase()}`)}</span>
        </div>
      ),
      mobileLabel: 'Status',
    },
    {
      id: 'dates',
      header: 'End date',
      render: (offer) => (
        <div className="offer-table__stack">
          <strong>{offer.expires_at ? formatDate(offer.expires_at) : 'No expiry'}</strong>
          <span>{offer.starts_at ? `Starts ${formatDate(offer.starts_at)}` : `Created ${formatDate(offer.created_at)}`}</span>
        </div>
      ),
      mobileLabel: 'Dates',
    },
  ];

  const openCreateModal = () => {
    setEditingOfferId(null);
    setEditingOfferKind('TEMPLATE');
    setForm(emptyOfferForm());
    setIsModalOpen(true);
  };

  const openEditModal = (offer: ManagedPersonalizedOffer) => {
    setEditingOfferId(offer.id);
    setEditingOfferKind(offer.record_kind);
    setForm(fromOffer(offer));
    setIsModalOpen(true);
  };

  const closeModal = () => {
    setEditingOfferId(null);
    setEditingOfferKind('TEMPLATE');
    setForm(emptyOfferForm());
    setIsModalOpen(false);
    setSubmitting(false);
  };

  const closeOfferDetails = () => {
    setSelectedOfferDetails(null);
    setGeneratedMatches([]);
    setGeneratedMatchesLoading(false);
  };

  const openOfferDetails = async (offer: ManagedPersonalizedOffer) => {
    setSelectedOfferDetails(offer);
    setGeneratedMatches([]);
    if (offer.record_kind !== 'GENERATED') {
      setGeneratedMatchesLoading(false);
      return;
    }
    setGeneratedMatchesLoading(true);
    try {
      const matches = await api.getGeneratedOfferMatches(token, restaurant.id, offer.id);
      setGeneratedMatches(matches);
    } catch (error: unknown) {
      onToast(
        'Generated matches unavailable',
        error instanceof ApiError ? error.message : 'Unable to load matched users right now.',
        'error',
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

    setSubmitting(true);
    try {
      const payload = buildPayload(form);
      const editingOffer = editingOfferId
        ? offers.find((offer) => offer.id === editingOfferId) ?? null
        : null;
      const saved = editingOfferId
        ? editingOfferKind === 'GENERATED' && editingOffer
          ? await api.updateGeneratedOfferState(
              token,
              restaurant.id,
              editingOfferId,
              buildGeneratedOfferPayload(form, editingOffer),
            )
          : await api.updateRestaurantOffer(token, restaurant.id, editingOfferId, payload)
        : await api.createRestaurantOffer(token, restaurant.id, payload);

      setOffers((current) => {
        if (!editingOfferId) {
          return [saved, ...current];
        }
        return current.map((offer) => (offer.id === saved.id ? saved : offer));
      });
      closeModal();
      onToast(
        editingOfferId ? 'Offer updated' : 'Offer created',
        editingOfferKind === 'GENERATED'
          ? `${saved.name} was updated for customer-facing surfaces.`
          : `${saved.name} is ready for generation and customer matching.`,
        'success',
      );
    } catch (error: unknown) {
      setSubmitting(false);
      onToast(
        'Offer save failed',
        error instanceof ApiError ? error.message : 'Unable to save this offer right now.',
        'error',
      );
    }
  };

  const updateOfferState = async (
    offer: ManagedPersonalizedOffer,
    nextState: PersonalizedOfferState,
    successMessage: string,
  ) => {
    try {
      const updated = offer.record_kind === 'GENERATED'
        ? await api.updateGeneratedOfferState(token, restaurant.id, offer.id, { state: nextState })
        : await api.updateRestaurantOffer(
            token,
            restaurant.id,
            offer.id,
            buildQuickTogglePayload(offer, nextState),
          );
      setOffers((current) => current.map((row) => (row.id === updated.id ? updated : row)));
      onToast('Offer updated', successMessage.replace('{name}', updated.name), 'success');
    } catch (error: unknown) {
      onToast(
        'Offer update failed',
        error instanceof ApiError ? error.message : 'Unable to change this offer state right now.',
        'error',
      );
    }
  };

  const confirmDeleteOffer = async () => {
    if (!offerPendingDelete || deleting) {
      return;
    }
    setDeleting(true);
    try {
      if (offerPendingDelete.record_kind === 'GENERATED') {
        await api.deleteGeneratedOffer(token, restaurant.id, offerPendingDelete.id);
      } else {
        await api.deleteRestaurantOffer(token, restaurant.id, offerPendingDelete.id);
      }
      setOffers((current) => current.filter((offer) => offer.id !== offerPendingDelete.id));
      onToast('Offer deleted', `${offerPendingDelete.name} was deleted.`, 'success');
      setOfferPendingDelete(null);
    } catch (error: unknown) {
      onToast(
        'Offer delete failed',
        error instanceof ApiError ? error.message : 'Unable to delete this offer right now.',
        'error',
      );
    } finally {
      setDeleting(false);
    }
  };

  return (
    <section className="admin-surface page-stack">
      <div className="panel__header">
        <div>
          <span className="eyebrow">Templates & generated campaigns</span>
          <h2>Offers & campaigns</h2>
          <p className="hint-text">
            Create reusable templates and inspect AI-generated campaigns with scope, discount rules, and clear validity windows.
          </p>
        </div>
        <button className="primary-button" onClick={openCreateModal} type="button">
          + Create offer
        </button>
      </div>

      <DataToolbar
        actions={<span className="toolbar-meta">{filteredOffers.length} offers</span>}
        filters={
          <select
            className="page-search page-search--select"
            onChange={(event) => setStateFilter(event.target.value as typeof stateFilter)}
            value={stateFilter}
          >
            <option value="ALL">All states</option>
            {OFFER_STATE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        }
        onSearchChange={setQuery}
        searchPlaceholder="Search offers, items, cuisines..."
        searchValue={query}
      />

      <ResponsiveTable
        actions={[
          {
            id: 'view',
            label: 'View',
            icon: Eye,
            onClick: (offer) => void openOfferDetails(offer),
          },
          {
            id: 'edit',
            label: 'Edit',
            icon: Edit3,
            onClick: openEditModal,
            hidden: (offer) => !offer.editable,
          },
          {
            id: 'enable',
            label: 'Enable',
            icon: PlayCircle,
            onClick: (offer) =>
              updateOfferState(offer, 'ACTIVE', '{name} is now active.'),
            hidden: (offer) => offer.effective_state === 'ACTIVE' || offer.effective_state === 'EXPIRED',
            tone: 'success',
          },
          {
            id: 'disable',
            label: 'Disable',
            icon: Ban,
            onClick: (offer) =>
              updateOfferState(offer, 'DISABLED', '{name} is now disabled.'),
            hidden: (offer) => offer.state === 'DISABLED' || offer.effective_state === 'EXPIRED',
          },
          {
            id: 'delete',
            label: 'Delete',
            icon: Trash2,
            onClick: (offer) => setOfferPendingDelete(offer),
            tone: 'danger',
          },
        ]}
        columns={columns}
        emptyDescription="Create the first reusable template for this restaurant."
        emptyTitle="No offers created yet"
        keyExtractor={(offer) => offer.id}
        loading={loading}
        mobileStatus={(offer) => <StatusPill status={offer.effective_state} />}
        mobileSubtitle={(offer) => `${offer.record_kind === 'GENERATED' ? 'AI generated' : 'Manual template'} · ${offer.restaurant_location_name ?? 'All branches'}`}
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

      {!loading && loadError ? (
        <EmptyPanel
          description={loadError}
          title="Unable to load offers right now"
        />
      ) : null}

      {selectedOfferDetails ? (
        <Modal onClose={closeOfferDetails} className="combo-detail-modal">
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">{selectedOfferDetails.record_kind === 'GENERATED' ? 'Generated campaign' : 'Offer details'}</span>
                <h2>{selectedOfferDetails.generated_title ?? selectedOfferDetails.name}</h2>
                <p className="hint-text">
                  {selectedOfferDetails.generated_subtitle ?? (selectedOfferDetails.record_kind === 'GENERATED' ? 'This campaign was generated from a reusable offer template.' : 'This manual template controls discount rules, scope, and validity for matching customers.')}
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
                    {selectedOfferDetails.record_kind === 'GENERATED'
                      ? selectedOfferDetails.manually_edited
                        ? 'AI generated campaign • Manually edited'
                        : 'AI generated campaign'
                      : 'Manual template'}
                  </span>
                </div>
                <div>
                  <strong>Offer type</strong>
                  <span>{formatOfferTypeLabel(selectedOfferDetails.offer_type)}</span>
                </div>
                <div>
                  <strong>Branch scope</strong>
                  <span>{selectedOfferDetails.restaurant_location_name ?? 'All branches'}</span>
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
                {selectedOfferDetails.record_kind === 'GENERATED' && selectedOfferDetails.manually_edited ? (
                  <div>
                    <strong>Edited by</strong>
                    <span>
                      {selectedOfferDetails.edited_by ?? 'Unknown'}
                      {selectedOfferDetails.edited_at ? ` · ${formatDate(selectedOfferDetails.edited_at)}` : ''}
                    </span>
                  </div>
                ) : null}
                <div>
                  <strong>Validity</strong>
                  <span>{formatValiditySummary(selectedOfferDetails)}</span>
                </div>
              </div>

              {selectedOfferDetails.record_kind === 'GENERATED' ? (
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
                <h2>{editingOfferId ? (isEditingGeneratedOffer ? 'Edit AI offer' : 'Edit offer') : 'Create offer'}</h2>
                <p className="hint-text">
                  {isEditingGeneratedOffer
                    ? 'Fine-tune AI-generated customer copy and availability timing. Discount logic and checkout validation remain backend-controlled.'
                    : 'Set discount rules, spend threshold, branch scope, and validity for this manual campaign.'}
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
              <label className="field form-grid__wide">
                <span>{isEditingGeneratedOffer ? 'Card title' : 'Offer title'}</span>
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
                        setForm((current) => ({ ...current, restaurant_location_id: event.target.value }))
                      }
                    >
                      <option value="">All branches</option>
                      {restaurant.locations.map((location) => (
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
                      disabled={form.discount_type === 'NONE' || form.discount_type === 'FREE_DELIVERY'}
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
                      disabled={form.discount_type !== 'PERCENTAGE'}
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
                  {submitting ? 'Saving...' : editingOfferId ? 'Save changes' : 'Create offer'}
                </button>
              </div>
            </form>
        </Modal>
      ) : null}

      <ConfirmDialog
        open={offerPendingDelete !== null}
        eyebrow="Delete offer"
        title="Are you sure you want to delete this offer?"
        description={
          offerPendingDelete
            ? `${offerPendingDelete.name} will be removed from customer surfaces and will stop applying immediately.`
            : ''
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
    </section>
  );
}
