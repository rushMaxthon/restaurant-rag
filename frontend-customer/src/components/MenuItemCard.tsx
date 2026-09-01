import { useState, type KeyboardEvent, type MouseEvent, type SyntheticEvent } from 'react';
import type { MenuItem } from '../types/app';
import { createPlaceholderImage, formatCurrency } from '../services/api';
import { getNewItemBadgeMeta } from '../utils/newItemBadges';
import { FavoriteButton } from './FavoriteButton';
import { DishRating } from './app/DishRating';

interface MenuItemCardProps {
  item: MenuItem;
  quantity: number;
  hasOfferAvailable?: boolean;
  onAdd: (item: MenuItem) => void;
  onDecrease: (item: MenuItem) => void;
  onToggleFavorite: (item: MenuItem) => void;
  onOpen: (item: MenuItem) => void;
  isFavorite: boolean;
  favoritePending?: boolean;
}

export function MenuItemCard({
  item,
  quantity,
  hasOfferAvailable = false,
  onAdd,
  onDecrease,
  onToggleFavorite,
  onOpen,
  isFavorite,
  favoritePending = false,
}: MenuItemCardProps) {
  const newItemMeta = getNewItemBadgeMeta(item);
  // Seeded menus carry image URLs that no longer resolve, and a failed `<img>`
  // paints its alt text across the row where the dish should be.
  const [imageFailed, setImageFailed] = useState(false);
  const handleKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onOpen(item);
    }
  };

  const stopPropagation = (event: SyntheticEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };

  const handleDecreaseClick = (event: MouseEvent<HTMLButtonElement>) => {
    stopPropagation(event);
    onDecrease(item);
  };

  const handleAddClick = (event: MouseEvent<HTMLButtonElement>) => {
    stopPropagation(event);
    onAdd(item);
  };

  const handleFavoriteClick = (event: MouseEvent<HTMLButtonElement>) => {
    stopPropagation(event);
    onToggleFavorite(item);
  };

  return (
    <article
      className="menu-item-card menu-item-card--interactive"
      onClick={() => onOpen(item)}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
    >
      <div className="menu-item-card__body">
        <div className="menu-item-card__badges">
          <span className={`food-dot ${item.is_veg ? 'food-dot--veg' : 'food-dot--nonveg'}`} />
          {newItemMeta.label ? <span className="chip chip--new">{newItemMeta.label}</span> : null}
          {hasOfferAvailable ? <span className="chip chip--offer">Offer</span> : null}
        </div>
        <div className="menu-item-card__copy">
          <h3>{item.name}</h3>
          <p>{item.description ?? 'Freshly prepared and ready for your next craving.'}</p>
        </div>
          <div className="menu-item-card__footer">
            <div className="menu-item-card__price">
              <strong>{formatCurrency(item.price)}</strong>
              <DishRating item={item} />
              <span>{item.is_bestseller ? 'Best Seller' : item.category}</span>
            </div>
          </div>
      </div>
      <div className="menu-item-card__aside">
        <div className="menu-item-card__media">
          <div className="menu-item-card__favorite">
            <FavoriteButton
              active={isFavorite}
              disabled={favoritePending}
              onClick={handleFavoriteClick}
              title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
            />
          </div>
          <img
            alt=""
            decoding="async"
            loading="lazy"
            onError={() => setImageFailed(true)}
            src={
              item.image_url && !imageFailed
                ? item.image_url
                : createPlaceholderImage(item.name)
            }
          />
        </div>
        {quantity > 0 ? (
          <div className="quantity-picker quantity-picker--menu" onClick={stopPropagation}>
            <button onClick={handleDecreaseClick} type="button">
              −
            </button>
            <span className="quantity-picker__count">{quantity}</span>
            <button disabled={!item.is_available} onClick={handleAddClick} type="button">
              +
            </button>
          </div>
        ) : (
          <button
            className="menu-item-card__add"
            disabled={!item.is_available}
            onClick={handleAddClick}
            type="button"
          >
            {item.is_available ? '+ ADD' : 'Out of stock'}
          </button>
        )}
      </div>
    </article>
  );
}
