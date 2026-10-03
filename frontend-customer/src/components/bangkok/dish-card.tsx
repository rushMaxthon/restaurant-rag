import { memo } from "react";
import { Link } from "@tanstack/react-router";
import { Heart, Minus, Plus, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { VegMark } from "./veg-mark";
import { type MenuItem } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";
import { useFavoriteIds, useToggleFavorite } from "@/lib/queries";
import { useMoney } from "@/lib/storefront";

/**
 * One dish, as a row rather than a photo card.
 *
 * The card it replaced led with a 16:10 photograph, and that was the wrong bet
 * for this product twice over.
 *
 * **Most of these dishes have no photograph worth showing.** Bhagwati's are
 * mostly listing-site thumbnails, Famous Chinese has none at all. A card whose
 * largest element is a picture will always look worst where the picture is
 * weakest, and every competitor in this category is built on photography we do
 * not have. A row degrades to text, which is what a menu is.
 *
 * **187 photo cards is also what made this page expensive.** The scroll work
 * earlier this week got the JavaScript down to nothing measurable and left
 * browser paint as the floor. A row paints a fraction of a card.
 *
 * So the photograph becomes a 56px thumbnail that appears ONLY when the dish
 * actually has one, and is simply absent otherwise — no generated tile
 * standing in for a picture. The motif still earns its place on the dish page,
 * where the alternative is a large empty rectangle.
 *
 * What leads instead is the veg mark. It is a mandated signal every customer
 * in this market reads before anything else, we already store it on every row,
 * and at this size it gives a long menu its rhythm without a single rule.
 */
function DishCardImpl({ item }: { item: MenuItem }) {
  // Prices in whatever this restaurant charges in.
  const money = useMoney();
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

  // A dish with sizes or add-ons cannot be added from a row — there is nothing
  // here to choose them with. Sending it to the detail page is honest; adding a
  // silent default and surprising them at checkout is not.
  const needsChoices = item.has_sizes || item.has_customizations;

  // Lines for this dish, so the row can show what is already in the cart
  // instead of an inert + that gives no feedback. Sized variants make several
  // lines; the stepper drives the most recent one.
  const lines = cart.filter((line) => line.itemId === item.id);
  const inCart = lines.reduce((sum, line) => sum + line.quantity, 0);
  const lastLine = lines[lines.length - 1];

  const photo = item.image_url?.trim();

  return (
    <article className="dish-row" data-sold-out={!item.is_available || undefined}>
      <VegMark className="dish-row__mark" veg={item.is_veg} />

      <div className="dish-row__body">
        <div className="dish-row__head">
          <Link
            className="dish-row__name font-display"
            params={{ itemId: item.id }}
            to="/menu/$itemId"
          >
            {item.name}
          </Link>

          {/* Outside the Link, so a tap saves the dish instead of opening it.
              Signed out there is nowhere to save it to, so it is not offered. */}
          {isAuthenticated && (
            <button
              aria-label={isFavorite ? `Remove ${item.name} from your usuals` : `Save ${item.name}`}
              aria-pressed={isFavorite}
              className="dish-row__heart"
              data-on={isFavorite}
              onClick={() => toggleFavorite.mutate({ menuItemId: item.id, next: !isFavorite })}
              type="button"
            >
              <Heart className="size-4" fill={isFavorite ? "currentColor" : "none"} />
            </button>
          )}
        </div>

        {(item.is_bestseller || item.is_new || item.rating) && (
          <p className="dish-row__meta">
            {item.is_bestseller && <span className="dish-chip dish-chip--hot">Bestseller</span>}
            {item.is_new && <span className="dish-chip dish-chip--new">New</span>}
            {item.rating && (
              <span className="dish-row__rating">
                <Star className="size-3.5 fill-current" />
                {item.rating}
                {item.rating_count > 0 && <span>({item.rating_count})</span>}
              </span>
            )}
          </p>
        )}

        {item.description?.trim() ? (
          <p className="dish-row__desc">{item.description}</p>
        ) : null}

        {/* Price and action share a line. Stacking the photograph above the
            button made every row as tall as both, which gave back most of
            what moving off cards had just won. */}
        <div className="dish-row__foot">
          <p className="dish-row__price money">
            {item.has_sizes ? `From ${money(item.price)}` : money(item.price)}
          </p>

          {!item.is_available ? (
            <span className="dish-row__soldout">Sold out</span>
          ) : conflicts || needsChoices ? (
            <Button asChild size="sm" variant="outline">
              <Link params={{ itemId: item.id }} to="/menu/$itemId">
                {conflicts ? "View" : "Choose"}
              </Link>
            </Button>
          ) : inCart > 0 && lastLine ? (
            <div className="qty-pill">
              <button
                aria-label={`Reduce ${item.name}`}
                className="qty-step"
                onClick={() => changeQuantity(lastLine.lineId, -1)}
                type="button"
              >
                <Minus className="size-4" />
              </button>
              <span className="qty-value">{inCart}</span>
              <button
                aria-label={`Add another ${item.name}`}
                className="qty-step"
                onClick={() => addItem(item)}
                type="button"
              >
                <Plus className="size-4" />
              </button>
            </div>
          ) : (
            <Button aria-label={`Add ${item.name}`} onClick={() => addItem(item)} size="icon">
              <Plus />
            </Button>
          )}
        </div>
      </div>

      {/* Rendered only when the dish HAS a photograph. Nothing stands in for
          one, because a generated tile in the shape of a picture is a promise
          the menu cannot keep. */}
      {photo && (
        <Link
          aria-label={item.name}
          className="dish-row__thumb"
          params={{ itemId: item.id }}
          to="/menu/$itemId"
        >
          <img alt="" decoding="async" loading="lazy" src={photo} />
        </Link>
      )}
    </article>
  );
}

/**
 * Memoised, and the menu is why.
 *
 * The rail's highlight lives in `MenuGrid`, the same component that renders
 * every row — so crossing a section boundary while scrolling set state there
 * and re-rendered all 187 of them. Measured on this restaurant's menu: a
 * ~190ms frame each time, once per section, which is exactly the stutter you
 * feel scrolling the page.
 *
 * `item` comes from the query cache and keeps its identity between renders,
 * so the comparison is a reference check and the whole subtree is skipped.
 * Everything else this reads — the cart, favourites, the currency — comes
 * from context, which `memo` does not block: a row still re-renders when the
 * quantity in the cart changes, which is the one time it has to.
 */
export const DishCard = memo(DishCardImpl);
