import { AppIcon } from '../AppIcon';
import { DishMedia } from './DishMedia';
import { FavoriteButton } from '../FavoriteButton';
import { DishRating } from './DishRating';
import { formatCurrency } from '../../services/api';
import type { MenuItem } from '../../types/app';

/**
 * The storefront's dish, everywhere the web app shows one.
 *
 * Replaces `DishCard` and `MenuItemCard`, which rendered the same record on the
 * home page and the restaurant page and had drifted apart: only one knew about
 * offers, and their `onDecrease` signatures disagreed — one passed the item, the
 * other its id — so a handler written against one mis-handled the other.
 *
 * `MenuGridCard` and `ItemCard` are deliberately NOT folded in. The first is a
 * faithful port of the phone's grid tile and is held to those metrics on
 * purpose; the second renders a `RecommendationItem`, which carries a
 * restaurant and opens one. Forcing either into this signature would be the
 * pile of variant props the original split was avoiding. They share this
 * component's tokens instead, so they look like one system without pretending
 * to be one component.
 *
 * `variant` changes density only — never what is shown. `grid` is the browse
 * tile with its photo; `compact` is the scannable row used in lists, where the
 * price and the add control sit at a fixed trailing edge so the eye runs down
 * one column instead of a ragged one.
 */
export function DishRow({
  item,
  quantity,
  onAdd,
  onDecrease,
  onOpen,
  hasOfferAvailable = false,
  isFavorite = false,
  favoritePending = false,
  onToggleFavorite,
  variant = 'grid',
}: {
  item: MenuItem;
  quantity: number;
  onAdd: (item: MenuItem) => void;
  onDecrease: (itemId: string) => void;
  onOpen: (itemId: string) => void;
  hasOfferAvailable?: boolean;
  isFavorite?: boolean;
  favoritePending?: boolean;
  onToggleFavorite?: (item: MenuItem) => void;
  variant?: 'grid' | 'compact';
}) {
  const classNames = ['dish-row', `dish-row--${variant}`];
  if (!item.is_available) {
    classNames.push('dish-row--out');
  }

  return (
    <article className={classNames.join(' ')}>
      <button
        aria-label={item.name}
        className="dish-row__media"
        onClick={() => onOpen(item.id)}
        type="button"
      >
        <DishMedia
          imageUrl={item.image_url ?? null}
          name={item.name}
          variant={variant === 'compact' ? 'compact' : 'grid'}
        />
        <span aria-hidden="true" className="dish-row__scrim" />
        <span
          className={item.is_veg ? 'diet-badge diet-badge--veg' : 'diet-badge'}
          title={item.is_veg ? 'Vegetarian' : 'Non-vegetarian'}
        />
      </button>

      {onToggleFavorite ? (
        <div className="dish-row__favorite">
          <FavoriteButton
            active={isFavorite}
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

      <div className="dish-row__body">
        <button className="dish-row__copy" onClick={() => onOpen(item.id)} type="button">
          <span className="dish-row__name">{item.name}</span>
          <span className="dish-row__meta">
            {item.category ? <span>{item.category}</span> : null}
            {/* At most one badge. Two stacked labels stop being a signal and start
                being noise, and "new" is the more perishable of the two — worth
                saying only while it is still true. */}
            {item.is_new ? (
              <span className="dish-row__badge dish-row__badge--new">New</span>
            ) : item.is_bestseller ? (
              <span className="dish-row__badge">Popular</span>
            ) : null}
            <DishRating item={item} />
            {hasOfferAvailable ? <span className="chip chip--offer">Offer</span> : null}
          </span>
        </button>

        <div className="dish-row__foot">
          <span className="dish-row__price">
            {/* A dish priced by size has no single price, so the row says which
                number it is showing rather than quoting the cheapest one flat. */}
            {item.has_sizes ? <small>From</small> : null}
            {formatCurrency(item.price)}
          </span>

          {!item.is_available ? (
            <span className="dish-row__sold-out">Sold out</span>
          ) : quantity > 0 ? (
            <span className="dish-row__stepper">
              <button aria-label="Remove one" onClick={() => onDecrease(item.id)} type="button">
                −
              </button>
              <span>{quantity}</span>
              <button aria-label="Add one" onClick={() => onAdd(item)} type="button">
                +
              </button>
            </span>
          ) : (
            <button className="dish-row__add" onClick={() => onAdd(item)} type="button">
              <AppIcon name="add" size={14} />
              Add
            </button>
          )}
        </div>
      </div>
    </article>
  );
}
