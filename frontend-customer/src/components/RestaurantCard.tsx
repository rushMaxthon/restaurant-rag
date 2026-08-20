import type { Restaurant } from '../types/app';
import { createPlaceholderImage, formatCurrency } from '../services/api';

interface RestaurantCardProps {
  restaurant: Restaurant;
  onOpen: (restaurantId: string) => void;
  disabled?: boolean;
  variant?: 'default' | 'compact';
}

export function RestaurantCard({
  restaurant,
  onOpen,
  disabled = false,
  variant = 'default',
}: RestaurantCardProps) {
  const isCompact = variant === 'compact';

  return (
    <button
      className={
        disabled
          ? `restaurant-card restaurant-card--${variant} restaurant-card--disabled`
          : `restaurant-card restaurant-card--${variant}`
      }
      disabled={disabled}
      onClick={() => onOpen(restaurant.id)}
      type="button"
      >
      <div className="restaurant-card__media">
        <img
          src={restaurant.cover_image_url ?? createPlaceholderImage(restaurant.name)}
          alt={restaurant.name}
        />
        <div className="restaurant-card__overlay" />
        <span className={`status-badge ${restaurant.is_open ? 'status-badge--open' : 'status-badge--closed'}`}>
          {restaurant.is_open ? 'Open' : 'Closed'}
        </span>
      </div>
      <div className="restaurant-card__body">
        <div className="restaurant-card__heading">
          <h3>{restaurant.name}</h3>
          <span>{isCompact ? restaurant.cuisine_type : restaurant.city}</span>
        </div>
        <p>{restaurant.cuisine_type}</p>
        <div className="restaurant-card__tags">
          <span className="micro-chip">{restaurant.cuisine_type}</span>
          <span className="micro-chip">{restaurant.city}</span>
        </div>
        <div className="restaurant-card__meta">
          <span>{restaurant.is_open ? 'Open now' : 'Closed for now'}</span>
          <span>Min {formatCurrency(restaurant.minimum_order_amount)}</span>
        </div>
      </div>
    </button>
  );
}
