import type { MouseEvent } from 'react';
import { createPlaceholderImage, formatCurrency } from '../../services/api';
import type { RecommendationItem } from '../../types/app';
import { getNewItemBadgeMeta } from '../../utils/newItemBadges';
import { FavoriteButton } from '../FavoriteButton';

interface ItemCardProps {
  item: RecommendationItem;
  onOpenRestaurant: (restaurantId: string) => void;
  onAddToCart: (item: RecommendationItem) => void;
  onToggleFavorite: (item: RecommendationItem) => void;
  isFavorite: boolean;
  favoritePending?: boolean;
  addDisabled?: boolean;
  disabled?: boolean;
}

export function ItemCard({
  item,
  onOpenRestaurant,
  onAddToCart,
  onToggleFavorite,
  isFavorite,
  favoritePending = false,
  addDisabled = false,
  disabled = false,
}: ItemCardProps) {
  const isAvailable = item.is_available !== false;
  const newItemMeta = getNewItemBadgeMeta(item);
  const primaryBadge = newItemMeta.label;
  const priceLabel =
    item.price_label ?? formatCurrency(item.display_price ?? item.price);
  const locationLabel =
    (item.available_locations_count ?? 1) > 1
      ? item.requires_location_selection
        ? `Available at ${item.available_locations_count} locations`
        : `Nearest: ${item.preferred_location_name ?? item.restaurant_location.branch_name}`
      : item.preferred_location_name ?? item.restaurant_location.branch_name;
  const handleAdd = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onAddToCart(item);
  };
  const handleFavorite = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    onToggleFavorite(item);
  };

  return (
    <article
      className={disabled ? 'home-item-card home-item-card--disabled' : 'home-item-card'}
    >
      <div className="home-item-card__media-wrap">
        <button
          className="home-item-card__media"
          disabled={disabled}
          onClick={() => onOpenRestaurant(item.restaurant_id)}
          type="button"
        >
          <div className="home-item-card__badge-row">
            <span className="home-item-card__match-badge">Match {Math.round(item.score * 100)}%</span>
          </div>
          <img
            alt={item.name}
            loading="lazy"
            src={item.image_url ?? createPlaceholderImage(item.name)}
          />
        </button>
        <div className="home-item-card__favorite">
          <FavoriteButton
            active={isFavorite}
            disabled={favoritePending}
            onClick={handleFavorite}
            title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
          />
        </div>
      </div>
      <div className="home-item-card__body">
        <button
          className="home-item-card__copy"
          disabled={disabled}
          onClick={() => onOpenRestaurant(item.restaurant_id)}
          type="button"
        >
          <div className="home-item-card__eyebrow-row">
            <span className="home-item-card__restaurant">{item.restaurant.name}</span>
            <span className={`food-dot ${item.is_veg ? 'food-dot--veg' : 'food-dot--nonveg'}`} />
          </div>
          <strong>{item.name}</strong>
          {primaryBadge ? (
            <div className="home-item-card__signal">
              <span className="chip chip--new">{primaryBadge}</span>
            </div>
          ) : null}
          <span className="home-item-card__location-meta">{locationLabel}</span>
        </button>
        <div className="home-item-card__footer">
          <div className="home-item-card__price-block">
            <strong>{priceLabel}</strong>
          </div>
          <div className="home-item-card__footer-actions">
            <button
              className="home-item-card__add"
              disabled={disabled || addDisabled || !isAvailable}
              onClick={handleAdd}
              type="button"
            >
              {isAvailable ? '+ Add' : 'Sold out'}
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}
