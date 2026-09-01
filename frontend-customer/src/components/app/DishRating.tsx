import { toNumber } from '../../services/api';
import type { MenuItem } from '../../types/app';

/**
 * A dish's star.
 *
 * Reads straight off the record and renders nothing when `rating` is null — a
 * dish nobody has rated yet shows no star rather than a zero, because "0.0 ★"
 * reads as "diners hated it" when it means "no one has said".
 */
export function DishRating({ item, className }: { item: MenuItem; className?: string }) {
  const rating = item.rating === null || item.rating === undefined ? null : toNumber(item.rating);

  if (rating === null) {
    return null;
  }

  return (
    <span
      className={className ? `dish-rating ${className}` : 'dish-rating'}
      title={
        item.rating_count > 0
          ? `${rating.toFixed(1)} from ${item.rating_count} ratings`
          : rating.toFixed(1)
      }
    >
      <span aria-hidden="true">★</span>
      {rating.toFixed(1)}
    </span>
  );
}
