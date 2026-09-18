import { Link } from "@tanstack/react-router";
import { Heart, Minus, Plus, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "./dish-image";
import { VegMark } from "./veg-mark";
import { formatMoney, type MenuItem } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";
import { useFavoriteIds, useToggleFavorite } from "@/lib/queries";

export function DishCard({ item }: { item: MenuItem }) {
  const { addItem, cart, changeQuantity, conflictsWithCart } = useBangkokStore();
  const { isAuthenticated } = useAuth();
  const favorites = useFavoriteIds(isAuthenticated);
  const toggleFavorite = useToggleFavorite();
  const isFavorite = favorites.data?.has(item.id) ?? false;

  // A concierge suggestion can belong to another restaurant, and one order can
  // only come from one kitchen. Rather than adding it and failing at checkout
  // — which is what used to happen — send them to the dish page, where the
  // choice to start a fresh cart is explained.
  const conflicts = conflictsWithCart(item);

  // A dish with sizes or add-ons cannot be added from a card — there is nothing
  // here to choose them with. Sending it to the detail page is honest; adding a
  // silent default and surprising them at checkout is not.
  const needsChoices = item.has_sizes || item.has_customizations;

  // Lines for this dish, so the card can show what is already in the cart
  // instead of an inert + that gives no feedback. Sized variants make several
  // lines; the stepper drives the most recent one.
  const lines = cart.filter((line) => line.itemId === item.id);
  const inCart = lines.reduce((sum, line) => sum + line.quantity, 0);
  const lastLine = lines[lines.length - 1];

  return (
    <article className="dish-card group relative flex flex-col overflow-hidden rounded-xl border border-border bg-surface">
      {/* Outside the Link, so a tap saves the dish instead of opening it.
          Signed out there is nowhere to save it to, so it is not offered. */}
      {isAuthenticated && (
        <button
          type="button"
          className="heart"
          data-on={isFavorite}
          aria-pressed={isFavorite}
          aria-label={isFavorite ? `Remove ${item.name} from your usuals` : `Save ${item.name}`}
          onClick={() => toggleFavorite.mutate({ menuItemId: item.id, next: !isFavorite })}
        >
          <Heart className="size-4" fill={isFavorite ? "currentColor" : "none"} />
        </button>
      )}
      <Link
        to="/menu/$itemId"
        params={{ itemId: item.id }}
        className="relative block overflow-hidden"
        aria-label={item.name}
      >
        <DishImage
          src={item.image_url}
          name={item.name}
          className="aspect-[16/10] transition-transform duration-500 group-hover:scale-[1.04]"
        />
        {(item.is_bestseller || item.is_new) && (
          <div className="absolute left-2.5 top-2.5 flex gap-1.5">
            {item.is_bestseller && <span className="dish-badge dish-badge--hot">Bestseller</span>}
            {item.is_new && <span className="dish-badge dish-badge--new">New</span>}
          </div>
        )}
        {!item.is_available && (
          <div className="absolute inset-0 grid place-items-center bg-overlay">
            <span className="rounded-full bg-surface px-3 py-1.5 text-xs font-extrabold uppercase tracking-wide">
              Unavailable
            </span>
          </div>
        )}
      </Link>

      <div className="flex flex-1 flex-col gap-2.5 p-4">
        <div className="min-w-0">
          <div className="mb-1 flex items-center gap-2">
            <VegMark veg={item.is_veg} />
            {item.rating && (
              <span className="flex items-center gap-1 text-sm font-semibold">
                <Star className="size-3.5 fill-primary text-primary" />
                {item.rating}
                {item.rating_count > 0 && (
                  <span className="text-xs font-medium text-muted">({item.rating_count})</span>
                )}
              </span>
            )}
          </div>
          <Link
            to="/menu/$itemId"
            params={{ itemId: item.id }}
            className="dish-title font-display text-lg font-bold leading-tight hover:text-primary"
          >
            {item.name}
          </Link>
        </div>

        <p className="line-clamp-2 min-h-10 text-sm leading-relaxed text-muted">
          {item.description}
        </p>

        <div className="mt-auto flex items-center justify-between gap-3 pt-1">
          <span className="money font-bold">
            {item.has_sizes ? `From ${formatMoney(item.price)}` : formatMoney(item.price)}
          </span>

          {!item.is_available ? (
            <span className="text-sm font-semibold text-muted">Sold out</span>
          ) : conflicts || needsChoices ? (
            <Button variant="outline" size="sm" asChild>
              <Link to="/menu/$itemId" params={{ itemId: item.id }}>
                {conflicts ? "View" : "Choose"}
              </Link>
            </Button>
          ) : inCart > 0 && lastLine ? (
            <div className="qty-pill">
              <button
                type="button"
                className="qty-step"
                aria-label={`Reduce ${item.name}`}
                onClick={() => changeQuantity(lastLine.lineId, -1)}
              >
                <Minus className="size-4" />
              </button>
              <span className="qty-value">{inCart}</span>
              <button
                type="button"
                className="qty-step"
                aria-label={`Add another ${item.name}`}
                onClick={() => addItem(item)}
              >
                <Plus className="size-4" />
              </button>
            </div>
          ) : (
            <Button aria-label={`Add ${item.name}`} size="icon" onClick={() => addItem(item)}>
              <Plus />
            </Button>
          )}
        </div>
      </div>
    </article>
  );
}
