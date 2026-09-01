import { useState } from 'react';
import { AppIcon } from '../AppIcon';
import { FavoriteButton } from '../FavoriteButton';
import { DishRating } from './DishRating';
import { formatCurrency } from '../../services/api';
import type { MenuItem } from '../../types/app';

/**
 * The home screen's dish tile.
 *
 * Split from `MenuGridCard` rather than grown out of it: that tile is a
 * faithful port of the phone's three-to-a-row grid and Search still renders it
 * at those metrics. The storefront wants a larger, photo-led card with the
 * badges and the favourite the phone puts on a different screen, and a single
 * component trying to be both would have been a pile of variant props.
 *
 * Everything on it is read off the record — `is_bestseller`, `is_new`,
 * `is_veg`, `is_available`. Nothing is invented for decoration: a star rating
 * the API does not return would be a number the customer has no reason to
 * trust.
 */
export function DishCard({
  item,
  quantity,
  onAdd,
  onDecrease,
  onOpen,
  isFavorite,
  favoritePending = false,
  onToggleFavorite,
}: {
  item: MenuItem;
  quantity: number;
  onAdd: (item: MenuItem) => void;
  onDecrease: (itemId: string) => void;
  onOpen: (itemId: string) => void;
  isFavorite?: boolean;
  favoritePending?: boolean;
  onToggleFavorite?: (item: MenuItem) => void;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const showFallbackArt = !item.image_url || imageFailed;

  return (
    <article className={item.is_available ? 'dish-card' : 'dish-card dish-card--out'}>
      <button
        aria-label={item.name}
        className="dish-card__media"
        onClick={() => onOpen(item.id)}
        type="button"
      >
        {showFallbackArt ? (
          <span className="dish-card__fallback">
            <AppIcon filled name="bag" size={36} />
          </span>
        ) : (
          <img
            alt=""
            decoding="async"
            loading="lazy"
            onError={() => setImageFailed(true)}
            src={item.image_url ?? undefined}
          />
        )}
        <span aria-hidden="true" className="dish-card__scrim" />
        <span
          className={item.is_veg ? 'diet-badge diet-badge--veg' : 'diet-badge'}
          title={item.is_veg ? 'Vegetarian' : 'Non-vegetarian'}
        />
        {/* At most one badge. Two stacked labels on a tile this size stop being
            a signal and start being noise, and "new" is the more perishable of
            the two — it is worth saying only while it is still true. */}
        <span className="dish-card__badges">
          {item.is_new ? (
            <span className="dish-card__badge dish-card__badge--new">New</span>
          ) : item.is_bestseller ? (
            <span className="dish-card__badge">Popular</span>
          ) : null}
        </span>
      </button>

      {onToggleFavorite ? (
        <div className="dish-card__favorite">
          <FavoriteButton
            active={Boolean(isFavorite)}
            disabled={favoritePending}
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onToggleFavorite(item);
            }}
            title={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
          />
        </div>
      ) : null}

      <div className="dish-card__body">
        <button className="dish-card__copy" onClick={() => onOpen(item.id)} type="button">
          <span className="dish-card__name">{item.name}</span>
          <span className="dish-card__meta">
            {item.category ? <span>{item.category}</span> : null}
            <DishRating item={item} />
          </span>
        </button>

        <div className="dish-card__foot">
          <span className="dish-card__price">
            {formatCurrency(item.price)}
            {/* A dish priced by size has no single price, so the tile says which
                number it is showing rather than quoting the small one flat. */}
            {item.has_sizes ? <small>From</small> : null}
          </span>

          {!item.is_available ? (
            <span className="dish-card__sold-out">Sold out</span>
          ) : quantity > 0 ? (
            <span className="dish-card__stepper">
              <button aria-label="Remove one" onClick={() => onDecrease(item.id)} type="button">
                −
              </button>
              <span>{quantity}</span>
              <button aria-label="Add one" onClick={() => onAdd(item)} type="button">
                +
              </button>
            </span>
          ) : (
            <button className="dish-card__add" onClick={() => onAdd(item)} type="button">
              <AppIcon name="add" size={14} />
              Add
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
