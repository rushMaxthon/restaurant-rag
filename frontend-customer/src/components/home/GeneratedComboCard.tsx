import { formatCurrency } from '../../services/api';
import type { GeneratedCombo } from '../../types/app';

interface GeneratedComboCardProps {
  combo: GeneratedCombo;
  onAddCombo: (combo: GeneratedCombo) => void;
  onOpenRestaurant: (restaurantId: string) => void;
  disabled?: boolean;
}

export function GeneratedComboCard({
  combo,
  onAddCombo,
  onOpenRestaurant,
  disabled = false,
}: GeneratedComboCardProps) {
  const visibleItems = combo.items.slice(0, 3);
  const remainingItems = combo.items.length - visibleItems.length;
  const popularityLabel =
    combo.order_count > 0 ? `${combo.order_count}+ ordered` : 'Fresh combo';

  return (
    <article className={disabled ? 'generated-combo-card generated-combo-card--disabled' : 'generated-combo-card'}>
      <div className="generated-combo-card__body">
        <div className="generated-combo-card__topline">
          <span className="generated-combo-card__pill generated-combo-card__pill--accent">
            Frequently ordered together
          </span>
          <span className="generated-combo-card__pill">Save {formatCurrency(combo.savings_amount)}</span>
        </div>
        <button
          className="generated-combo-card__title"
          disabled={disabled}
          onClick={() => onOpenRestaurant(combo.restaurant_id)}
          type="button"
        >
          {combo.combo_name}
        </button>
        <button
          className="generated-combo-card__restaurant"
          disabled={disabled}
          onClick={() => onOpenRestaurant(combo.restaurant_id)}
          type="button"
        >
          {combo.restaurant_name}
        </button>
        <div className="generated-combo-card__items">
          {visibleItems.map((item) => (
            <span className="generated-combo-card__item-chip" key={item.menu_item_id}>
              {item.quantity > 1 ? `${item.quantity}x ` : ''}
              {item.name}
            </span>
          ))}
          {remainingItems > 0 ? (
            <span className="generated-combo-card__item-chip generated-combo-card__item-chip--muted">
              +{remainingItems} more
            </span>
          ) : null}
        </div>
        <div className="generated-combo-card__meta">
          <span className="generated-combo-card__stat">{popularityLabel}</span>
          <span className="generated-combo-card__count">
            {combo.items.length} item{combo.items.length === 1 ? '' : 's'}
          </span>
        </div>
        <div className="generated-combo-card__footer">
          <div className="generated-combo-card__price-block">
            <strong>{formatCurrency(combo.suggested_combo_price)}</strong>
            <span>
              {combo.original_total_price !== combo.suggested_combo_price
                ? `Was ${formatCurrency(combo.original_total_price)}`
                : 'Bundle price'}
            </span>
          </div>
          <button
            className="generated-combo-card__add"
            disabled={disabled}
            onClick={() => onAddCombo(combo)}
            type="button"
          >
            + Add
          </button>
        </div>
      </div>
    </article>
  );
}
