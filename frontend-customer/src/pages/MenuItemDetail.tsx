import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { DishCard } from '../components/app/DishCard';
import { DishRating } from '../components/app/DishRating';
import { SectionHeader } from '../components/app/SectionHeader';
import { FavoriteButton } from '../components/FavoriteButton';
import { useAppStore } from '../hooks/useAppStore';
import { ApiError, api, createPlaceholderImage, formatCurrency, toNumber } from '../services/api';
import { Skeleton } from '../components/Skeleton';
import type {
  CartSelectedOption,
  MenuItem,
  MenuItemCustomizationGroup,
  MenuItemCustomizationOption,
  Restaurant,
} from '../types/app';
import { checkAuthAndRedirect } from '../utils/authRedirect';
import { getNewItemBadgeMeta } from '../utils/newItemBadges';
import {
  isCustomizableMenuItem,
  buildLineItemId,
  calculateUnitPrice,
  findCustomizationOption,
  formatCustomizationSummary,
  getActiveCustomizationGroups,
  getDefaultSelectedSize,
  validateCustomizationSelection,
} from '../utils/menuItemCustomization';

interface MenuItemDetailPageProps {
  itemId: string;
  token: string | null;
  onNavigate: (path: string) => void;
}

export function MenuItemDetailPage({
  itemId,
  token,
  onNavigate,
}: MenuItemDetailPageProps) {
  const {
    cart,
    favoritesHydrated,
    isAuthenticated,
    isFavorite,
    isFavoritePending,
    pushToast,
    requestAddToCart,
    setPendingAuthRedirectPath,
    toggleFavorite,
    updateCartQuantity,
  } = useAppStore();
  const [item, setItem] = useState<MenuItem | null>(null);
  const [restaurant, setRestaurant] = useState<Restaurant | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedSize, setSelectedSize] = useState<{
    id: string;
    name: string;
    price: number | string;
  } | null>(null);
  const [selectedOptions, setSelectedOptions] = useState<CartSelectedOption[]>([]);
  const [suggestions, setSuggestions] = useState<MenuItem[]>([]);

  useEffect(() => {
    const controller = new AbortController();

    async function loadMenuItemDetail() {
      setLoading(true);
      setError(null);
      setNotFound(false);
      setItem(null);
      setRestaurant(null);

      try {
        const menuItem = await api.getMenuItem(itemId, token, controller.signal);
        if (controller.signal.aborted) {
          return;
        }

        setItem(menuItem);

        try {
          const restaurantRow = await api.getRestaurant(menuItem.restaurant_id, controller.signal);
          if (!controller.signal.aborted) {
            setRestaurant(restaurantRow);
          }
        } catch {
          if (!controller.signal.aborted) {
            setRestaurant(null);
          }
        }
      } catch (nextError) {
        if (controller.signal.aborted) {
          return;
        }

        if (nextError instanceof ApiError && nextError.status === 404) {
          setNotFound(true);
        } else {
          setError(nextError instanceof ApiError ? nextError.message : 'Unable to load this item right now.');
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void loadMenuItemDetail();

    return () => {
      controller.abort();
    };
  }, [itemId, reloadKey, token]);

  /* The rest of the branch's menu, ranked for this dish.
     Same category first — somebody reading a curry is closest to ordering
     another curry — then the kitchen's bestsellers, then whatever diners have
     actually rated highest. It is the branch's own menu rather than a
     recommendation call: the customer is standing in front of one dish at one
     branch, and a suggestion they cannot add to this order is worse than none.
     A failure here leaves the rail empty and the page unaffected. */
  useEffect(() => {
    if (!item) {
      setSuggestions([]);
      return;
    }

    const controller = new AbortController();

    async function loadSuggestions(currentItem: MenuItem) {
      try {
        const rows = await api.getMenuItems(
          currentItem.restaurant_id,
          token,
          controller.signal,
          currentItem.restaurant_location_id,
        );
        if (controller.signal.aborted) {
          return;
        }

        const ranked = rows
          .filter((row) => row.id !== currentItem.id && row.is_available)
          .sort((left, right) => {
            const sameCategory = Number(right.category === currentItem.category)
              - Number(left.category === currentItem.category);
            if (sameCategory !== 0) {
              return sameCategory;
            }
            const bestseller = Number(right.is_bestseller) - Number(left.is_bestseller);
            if (bestseller !== 0) {
              return bestseller;
            }
            const rating = toNumber(right.rating ?? 0) - toNumber(left.rating ?? 0);
            if (rating !== 0) {
              return rating;
            }
            return toNumber(right.popularity_score ?? 0) - toNumber(left.popularity_score ?? 0);
          })
          .slice(0, 8);

        setSuggestions(ranked);
      } catch {
        if (!controller.signal.aborted) {
          setSuggestions([]);
        }
      }
    }

    void loadSuggestions(item);

    return () => {
      controller.abort();
    };
  }, [item, token]);

  useEffect(() => {
    if (!item) {
      setSelectedSize(null);
      setSelectedOptions([]);
      return;
    }
    setSelectedSize(getDefaultSelectedSize(item));
    setSelectedOptions([]);
  }, [item]);

  const activeGroups = useMemo(
    () => (item ? getActiveCustomizationGroups(item, selectedSize?.id ?? null) : []),
    [item, selectedSize?.id],
  );
  const currentLineItemId = useMemo(
    () => (
      item
        ? buildLineItemId({
            menuItemId: item.id,
            selectedSizeId: selectedSize?.id ?? null,
            selectedOptions,
          })
        : null
    ),
    [item, selectedOptions, selectedSize?.id],
  );
  const currentCartEntry = useMemo(
    () => (currentLineItemId ? cart.items.find((entry) => entry.id === currentLineItemId) ?? null : null),
    [cart.items, currentLineItemId],
  );
  const quantity = currentCartEntry?.quantity ?? 0;
  const liveUnitPrice = useMemo(
    () => (
      item
        ? calculateUnitPrice({
            menuItem: item,
            selectedSize,
            selectedOptions,
          })
        : 0
    ),
    [item, selectedOptions, selectedSize],
  );
  const cartQuantities = useMemo(
    () =>
      cart.items.reduce((map, entry) => {
        map.set(entry.menuItem.id, (map.get(entry.menuItem.id) ?? 0) + entry.quantity);
        return map;
      }, new Map<string, number>()),
    [cart.items],
  );
  const customizationSummary = useMemo(
    () => formatCustomizationSummary(selectedSize, selectedOptions),
    [selectedOptions, selectedSize],
  );

  const upsertOption = (
    group: MenuItemCustomizationGroup,
    option: MenuItemCustomizationOption,
    quantityValue: number,
  ) => {
    setSelectedOptions((current) => {
      const next = current.filter((entry) => entry.optionId !== option.id);
      next.push({
        groupId: group.id,
        groupTitle: group.title,
        selectionType: group.selection_type,
        optionId: option.id,
        optionName: option.name,
        extraPrice: option.extra_price,
        quantity: quantityValue,
        isCountable: option.is_countable,
      });
      return next;
    });
  };

  const removeOption = (optionId: string) => {
    setSelectedOptions((current) => current.filter((entry) => entry.optionId !== optionId));
  };

  const handleSizeSelect = (sizeId: string) => {
    if (!item) {
      return;
    }
    const nextSize = item.sizes.find((size) => size.id === sizeId && size.is_active);
    if (!nextSize) {
      return;
    }
    setSelectedSize({
      id: nextSize.id,
      name: nextSize.name,
      price: nextSize.price,
    });
    setSelectedOptions([]);
  };

  const handleOptionPress = (
    group: MenuItemCustomizationGroup,
    option: MenuItemCustomizationOption,
  ) => {
    const existing = selectedOptions.find((entry) => entry.optionId === option.id);
    if (group.selection_type === 'SINGLE') {
      if (existing && !group.is_required) {
        setSelectedOptions((current) => current.filter((entry) => entry.groupId !== group.id));
        return;
      }
      setSelectedOptions((current) => {
        const next = current.filter((entry) => entry.groupId !== group.id);
        next.push({
          groupId: group.id,
          groupTitle: group.title,
          selectionType: group.selection_type,
          optionId: option.id,
          optionName: option.name,
          extraPrice: option.extra_price,
          quantity: 1,
          isCountable: option.is_countable,
        });
        return next;
      });
      return;
    }

    if (existing) {
      removeOption(option.id);
      return;
    }

    const groupSelections = selectedOptions.filter((entry) => entry.groupId === group.id);
    if (groupSelections.length >= group.max_selection) {
      pushToast(
        'Selection limit reached',
        `${group.title} allows up to ${group.max_selection} choices.`,
        'info',
      );
      return;
    }

    upsertOption(group, option, 1);
  };

  const handleOptionQuantityChange = (optionId: string, delta: number) => {
    if (!item) {
      return;
    }
    const resolved = findCustomizationOption(item, selectedSize?.id ?? null, optionId);
    if (!resolved) {
      return;
    }
    const existing = selectedOptions.find((entry) => entry.optionId === optionId);
    if (!existing) {
      if (delta > 0) {
        upsertOption(resolved.group, resolved.option, 1);
      }
      return;
    }
    if (!existing.isCountable) {
      return;
    }
    const nextQuantity = existing.quantity + delta;
    if (nextQuantity <= 0) {
      removeOption(optionId);
      return;
    }
    upsertOption(resolved.group, resolved.option, nextQuantity);
  };

  if (loading) {
    return (
      <div className="page-stack menu-detail-page">
        <div className="menu-detail-back-row">
          <button className="restaurant-back-button menu-detail-back" onClick={() => onNavigate('/')} type="button">
            ← Back
          </button>
        </div>
        <section className="section-card menu-detail-card menu-detail-card--loading">
          <Skeleton className="menu-detail-card__media-skeleton" />
          <div className="menu-detail-card__copy">
            <Skeleton className="menu-detail-card__title-skeleton" />
            <Skeleton className="menu-detail-card__meta-skeleton" />
            <Skeleton className="menu-detail-card__body-skeleton" />
            <Skeleton className="menu-detail-card__body-skeleton menu-detail-card__body-skeleton--short" />
          </div>
        </section>
        <div className="menu-detail-bar menu-detail-bar--loading">
          <Skeleton className="menu-detail-bar__price-skeleton" />
          <Skeleton className="menu-detail-bar__action-skeleton" />
        </div>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="page-stack menu-detail-page">
        <section className="section-card">
          <div className="empty-state empty-state--with-actions">
            <strong>This menu item is no longer available.</strong>
            <span>It may have sold out, been removed, or changed restaurants.</span>
            <div className="empty-state__actions">
              <button
                className="primary-button primary-button--small"
                onClick={() => onNavigate('/')}
                type="button"
              >
                Browse restaurants
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  if (error || !item) {
    return (
      <div className="page-stack menu-detail-page">
        <section className="section-card">
          <div className="empty-state empty-state--with-actions">
            <strong>We couldn’t load this item right now.</strong>
            <span>{error ?? 'Please try again in a moment.'}</span>
            <div className="empty-state__actions">
              <button
                className="primary-button primary-button--small"
                onClick={() => setReloadKey((value) => value + 1)}
                type="button"
              >
                Retry
              </button>
              <button
                className="secondary-button secondary-button--small"
                onClick={() => onNavigate('/')}
                type="button"
              >
                Back to home
              </button>
            </div>
          </div>
        </section>
      </div>
    );
  }

  const restaurantName = restaurant?.name ?? 'Restaurant';
  const newItemMeta = getNewItemBadgeMeta(item);
  const requireAuth = (redirectPath: string) =>
    checkAuthAndRedirect({
      isAuthenticated,
      redirectPath,
      onNavigate,
      pushToast,
      setPendingAuthRedirectPath,
    });

  const handleAdd = (event?: MouseEvent<HTMLButtonElement>) => {
    event?.preventDefault();
    event?.stopPropagation();

    if (!requireAuth(`/menu-item/${item.id}`)) {
      return;
    }

    const validationError = validateCustomizationSelection({
      menuItem: item,
      selectedSize,
      selectedOptions,
    });
    if (validationError) {
      pushToast('Complete your selection', validationError, 'info');
      return;
    }

    void requestAddToCart({
      menuItem: item,
      restaurantId: item.restaurant_id,
      restaurantName,
      selectedSize,
      selectedOptions,
      unitPrice: liveUnitPrice,
    });
  };

  const handleFavorite = async (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();

    if (!requireAuth(`/menu-item/${item.id}`)) {
      return;
    }

    try {
      const nextFavorite = await toggleFavorite({ menuItemId: item.id });
      pushToast(
        nextFavorite ? 'Saved to favorites' : 'Removed from favorites',
        nextFavorite ? `${item.name} is now in your favorites.` : `${item.name} was removed from favorites.`,
        'success',
      );
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Unable to update favorites right now.';
      pushToast('Favorites unavailable', message, 'error');
    }
  };

  const handleSuggestionAdd = (suggestion: MenuItem) => {
    if (!requireAuth(`/menu-item/${item.id}`)) {
      return;
    }

    /* A dish with sizes or option groups cannot be added from a tile without
       silently picking for the customer, so the tile opens it instead. */
    if (isCustomizableMenuItem(suggestion)) {
      onNavigate(`/menu-item/${suggestion.id}`);
      return;
    }

    void requestAddToCart({
      menuItem: suggestion,
      restaurantId: suggestion.restaurant_id,
      restaurantName,
    });
  };

  const handleSuggestionFavorite = async (suggestion: MenuItem) => {
    if (!requireAuth(`/menu-item/${item.id}`)) {
      return;
    }

    try {
      const nextFavorite = await toggleFavorite({ menuItemId: suggestion.id });
      pushToast(
        nextFavorite ? 'Saved to favorites' : 'Removed from favorites',
        nextFavorite
          ? `${suggestion.name} is now in your favorites.`
          : `${suggestion.name} was removed from favorites.`,
        'success',
      );
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Unable to update favorites right now.';
      pushToast('Favorites unavailable', message, 'error');
    }
  };

  return (
    <div className="page-stack menu-detail-page">
      <div className="menu-detail-back-row">
        <button
          className="restaurant-back-button menu-detail-back"
          onClick={() => onNavigate(`/restaurant/${item.restaurant_id}`)}
          type="button"
        >
          ← Back to menu
        </button>
      </div>

      <section className="section-card menu-detail-card">
        <div className="menu-detail-card__media">
          <img loading="lazy" decoding="async"
            src={item.image_url ?? createPlaceholderImage(item.name)}
            alt={item.name}
          />
        </div>
        <div className="menu-detail-card__copy">
          <div className="menu-detail-card__badges">
            <span className={`food-dot ${item.is_veg ? 'food-dot--veg' : 'food-dot--nonveg'}`} />
            <span className="chip chip--muted">{item.category}</span>
            {newItemMeta.label ? <span className="chip chip--new">{newItemMeta.label}</span> : null}
            {!item.is_available ? <span className="chip chip--muted">Out of stock</span> : null}
          </div>
          <div className="menu-detail-card__headline">
            <div>
              <span className="eyebrow">{restaurant?.name ?? 'Fresh pick'}</span>
              <h1>{item.name}</h1>
            </div>
            <div className="menu-detail-card__headline-actions">
              {/* Only when there is something to say. Falling back to the
                  category printed the same word twice: the badge row above
                  already carries it. */}
              {item.is_bestseller ? <span className="menu-detail-rating">Best Seller</span> : null}
              <FavoriteButton
                active={favoritesHydrated ? isFavorite(item.id) : item.is_favorite}
                disabled={isFavoritePending(item.id)}
                onClick={handleFavorite}
                title={(favoritesHydrated ? isFavorite(item.id) : item.is_favorite) ? 'Remove from favorites' : 'Add to favorites'}
              />
            </div>
          </div>
          <p className="menu-detail-description">
            {item.description ?? 'Freshly prepared with balanced flavors, quality ingredients, and just the right amount of comfort.'}
          </p>
          <div className="menu-detail-meta">
            <div>
              <span>{item.has_sizes ? 'Starting at' : 'Price'}</span>
              <strong>{formatCurrency(item.has_sizes ? liveUnitPrice : item.price)}</strong>
            </div>
            {/* `popularity_score` used to sit here. It is an internal ranking
                number — "50" tells a customer nothing and invites them to read
                it as a rating out of a hundred. The star is what diners
                actually said, and it renders only once somebody has said it. */}
            {item.rating !== null && item.rating !== undefined ? (
              <div>
                <span>Rating</span>
                <strong>
                  <DishRating item={item} />
                  {item.rating_count > 0 ? (
                    <small className="menu-detail-meta__note">
                      {item.rating_count} {item.rating_count === 1 ? 'rating' : 'ratings'}
                    </small>
                  ) : null}
                </strong>
              </div>
            ) : null}
            <div>
              <span>Prep time</span>
              <strong>18-24 min</strong>
            </div>
          </div>

          {item.has_sizes && item.sizes.length > 0 ? (
            <div className="menu-customization-card">
              <div className="menu-customization-card__header">
                <div>
                  <h3>Choose a size</h3>
                  <p>Select the base portion before adding toppings.</p>
                </div>
              </div>
              <div className="menu-size-grid">
                {item.sizes
                  .filter((size) => size.is_active)
                  .map((size) => {
                    const selected = selectedSize?.id === size.id;
                    return (
                      <button
                        key={size.id}
                        className={`menu-size-chip${selected ? ' menu-size-chip--active' : ''}`}
                        onClick={() => handleSizeSelect(size.id)}
                        type="button"
                      >
                        <span>{size.name}</span>
                        <strong>{formatCurrency(size.price)}</strong>
                      </button>
                    );
                  })}
              </div>
            </div>
          ) : null}

          {activeGroups.map((group) => {
            const groupSelections = selectedOptions.filter((entry) => entry.groupId === group.id);
            return (
              <div className="menu-customization-card" key={group.id}>
                <div className="menu-customization-card__header">
                  <div>
                    <h3>{group.title}</h3>
                    <p>
                      {group.selection_type === 'SINGLE'
                        ? 'Choose one'
                        : `Choose ${group.min_selection}-${group.max_selection}`}
                      {group.is_required ? ' • Required' : ' • Optional'}
                    </p>
                  </div>
                </div>
                <div className="menu-option-list">
                  {group.options
                    .filter((option) => option.is_active)
                    .map((option) => {
                      const selection = groupSelections.find((entry) => entry.optionId === option.id);
                      const selected = Boolean(selection);
                      return (
                        <div
                          key={option.id}
                          className={`menu-option-card${selected ? ' menu-option-card--active' : ''}`}
                          onClick={() => handleOptionPress(group, option)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter' || event.key === ' ') {
                              event.preventDefault();
                              handleOptionPress(group, option);
                            }
                          }}
                          role="button"
                          tabIndex={0}
                        >
                          <span
                            className={`menu-option-card__indicator menu-option-card__indicator--${group.selection_type.toLowerCase()}${selected ? ' menu-option-card__indicator--active' : ''}`}
                          />
                          <span className="menu-option-card__copy">
                            <strong>{option.name}</strong>
                            <small>
                              {toNumber(option.extra_price) > 0
                                ? `+ ${formatCurrency(option.extra_price)}`
                                : 'Included'}
                            </small>
                          </span>
                          {option.is_countable && selected ? (
                            <span
                              className="menu-option-stepper"
                              onClick={(event) => event.stopPropagation()}
                            >
                              <button
                                onClick={() => handleOptionQuantityChange(option.id, -1)}
                                type="button"
                              >
                                −
                              </button>
                              <strong>{selection?.quantity ?? 1}</strong>
                              <button
                                onClick={() => handleOptionQuantityChange(option.id, 1)}
                                type="button"
                              >
                                +
                              </button>
                            </span>
                          ) : null}
                        </div>
                      );
                    })}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <div className="menu-detail-bar">
        <div className="menu-detail-bar__summary">
          <span>{quantity > 0 ? `${quantity} in cart` : 'Ready to order'}</span>
          <strong>{formatCurrency(liveUnitPrice * Math.max(quantity, 1))}</strong>
          {customizationSummary.length > 0 ? (
            <small className="menu-detail-bar__selection-summary">
              {customizationSummary.join(' • ')}
            </small>
          ) : null}
        </div>
        <div className="menu-detail-bar__actions">
          {quantity > 0 ? (
            <>
              <div className="quantity-picker menu-detail-bar__picker">
                <button
                  onClick={(event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    if (currentLineItemId) {
                      updateCartQuantity(currentLineItemId, quantity - 1);
                    }
                  }}
                  type="button"
                >
                  −
                </button>
                <span className="quantity-picker__count">{quantity}</span>
                <button disabled={!item.is_available} onClick={handleAdd} type="button">
                  +
                </button>
              </div>
              <button
                className="secondary-button menu-detail-bar__cart-link"
                onClick={() => {
                  if (requireAuth('/cart')) {
                    onNavigate('/cart');
                  }
                }}
                type="button"
              >
                View cart
              </button>
            </>
          ) : (
            <button
              className="primary-button menu-detail-bar__cta"
              disabled={!item.is_available}
              onClick={handleAdd}
              type="button"
            >
              {item.is_available ? `Add to cart · ${formatCurrency(liveUnitPrice)}` : 'Out of stock'}
            </button>
          )}
        </div>
      </div>

      {suggestions.length > 0 ? (
        <section className="menu-detail-suggestions">
          <SectionHeader
            title="Goes well with this"
            subtitle={`More from ${restaurantName}, starting with the rest of the ${item.category.toLowerCase()}.`}
            actionLabel="See full menu"
            onAction={() => onNavigate(`/restaurant/${item.restaurant_id}`)}
          />
          <div className="home-horizontal-row menu-detail-suggestions__row">
            {suggestions.map((suggestion) => (
              <DishCard
                favoritePending={isFavoritePending(suggestion.id)}
                isFavorite={favoritesHydrated ? isFavorite(suggestion.id) : suggestion.is_favorite}
                item={suggestion}
                key={suggestion.id}
                onAdd={handleSuggestionAdd}
                onDecrease={(menuItemId) =>
                  updateCartQuantity(menuItemId, (cartQuantities.get(menuItemId) ?? 0) - 1)
                }
                onOpen={(menuItemId) => onNavigate(`/menu-item/${menuItemId}`)}
                onToggleFavorite={handleSuggestionFavorite}
                quantity={
                  isCustomizableMenuItem(suggestion) ? 0 : cartQuantities.get(suggestion.id) ?? 0
                }
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}
