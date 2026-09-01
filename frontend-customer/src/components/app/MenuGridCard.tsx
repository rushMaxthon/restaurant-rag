import { useState } from 'react';
import { AppIcon } from '../AppIcon';
import { formatCurrency } from '../../services/api';
import type { MenuItem } from '../../types/app';

/**
 * `mobile/src/components/home/MenuGridCard.tsx`.
 *
 * Three to a row, the photo at 0.82 of the tile width, and the ADD control
 * floating over the photo's bottom edge — including the overhang, which is what
 * makes the pill read as sitting on the card rather than inside the image.
 */
export function MenuGridCard({
  item,
  quantity,
  onAdd,
  onDecrease,
  onOpen,
}: {
  item: MenuItem;
  quantity: number;
  onAdd: (item: MenuItem) => void;
  onDecrease: (itemId: string) => void;
  onOpen: (itemId: string) => void;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  // A missing or broken photo gets styled art rather than an empty grey box,
  // which is what most seeded dishes hit today.
  const showFallbackArt = !item.image_url || imageFailed;

  return (
    <article className="dish-tile">
      {/* The photo clips to the card's top corners, so the ADD control cannot
          live inside it — it overhangs the photo's bottom edge by design. This
          wrapper is what both are positioned against. */}
      <div className="dish-tile__top">
      <button
        aria-label={item.name}
        className="dish-tile__media"
        onClick={() => onOpen(item.id)}
        type="button"
      >
        {showFallbackArt ? (
          <span className="dish-tile__fallback">
            <AppIcon filled name="bag" size={30} />
          </span>
        ) : (
          <img loading="lazy" decoding="async" alt="" onError={() => setImageFailed(true)} src={item.image_url ?? undefined} />
        )}
        <span aria-hidden="true" className="dish-tile__scrim" />
        <span
          className={item.is_veg ? 'diet-badge diet-badge--veg' : 'diet-badge'}
          title={item.is_veg ? 'Vegetarian' : 'Non-vegetarian'}
        />
      </button>

      {!item.is_available ? (
        <span className="dish-tile__sold-out">Sold out</span>
      ) : quantity > 0 ? (
        <span className="dish-tile__stepper">
          <button aria-label="Remove one" onClick={() => onDecrease(item.id)} type="button">
            −
          </button>
          <span>{quantity}</span>
          <button aria-label="Add one" onClick={() => onAdd(item)} type="button">
            +
          </button>
        </span>
      ) : (
        <button className="dish-tile__add" onClick={() => onAdd(item)} type="button">
          ADD <span aria-hidden="true">+</span>
        </button>
      )}
      </div>

      <button className="dish-tile__body" onClick={() => onOpen(item.id)} type="button">
        <span className="dish-tile__name">{item.name}</span>
        <span className="dish-tile__price">{formatCurrency(item.price)}</span>
      </button>
    </article>
  );
}
