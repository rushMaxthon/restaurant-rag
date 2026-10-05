import { Plus } from "lucide-react";

import { DishImage } from "@/components/bangkok/dish-image";
import { VegMark } from "@/components/bangkok/veg-mark";
import { Button } from "@/components/ui/button";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useMenuItems } from "@/lib/queries";
import { useMoney } from "@/lib/storefront";

/** How many to offer. Six fills the column beside a short cart without
 *  becoming a second menu, which is a page we already have. */
const OFFER = 6;

/**
 * A few more things from the same kitchen, under the cart.
 *
 * The cart is the emptiest page on the site and the one where the customer is
 * most willing to add something: three items left a column of white running
 * the height of the summary beside it, which reads as a page that has
 * finished with you.
 *
 * Everything here is real menu data from the branch already being ordered
 * from — no second request, because the menu query is the one the menu page
 * has already warmed, and no scoring, because a recommendation this page
 * cannot explain is worse than an honest "also from this kitchen".
 *
 * Three rules about what can appear, each of which would otherwise produce a
 * tap that fails:
 *
 * - Nothing already in the cart. Offering someone what they have just added
 *   reads as though the page was not paying attention.
 * - Nothing that needs a size or an add-on chosen. There is no room to choose
 *   one here, and adding a silent default is the trick this codebase refuses
 *   everywhere else.
 * - Nothing unavailable, which is a sold-out dish dressed as an offer.
 *
 * Bestsellers first, then whatever else qualifies, so a kitchen that has
 * marked none still fills the row.
 */
export function CartSuggestions() {
  const money = useMoney();
  const { addItem, cart, restaurantId, branchId } = useBangkokStore();
  const menuQuery = useMenuItems(restaurantId, branchId || undefined);

  const inCart = new Set(cart.map((line) => line.itemId));
  const eligible = (menuQuery.data ?? []).filter(
    (item) =>
      item.is_available &&
      !inCart.has(item.id) &&
      !item.has_sizes &&
      !item.has_customizations,
  );

  // A stable order, so the row does not reshuffle itself as the cart changes.
  const offers = [
    ...eligible.filter((item) => item.is_bestseller),
    ...eligible.filter((item) => !item.is_bestseller),
  ].slice(0, OFFER);

  if (offers.length === 0) return null;

  return (
    <section className="cart-more">
      <h2 className="font-display cart-more__title">Add something else</h2>
      <p className="cart-more__note">From the same kitchen, ready with your order.</p>

      <ul className="cart-more__grid">
        {offers.map((item) => (
          <li className="cart-more__item" key={item.id}>
            <DishImage
              className="cart-more__shot"
              name={item.name}
              src={item.image_url}
              category={item.category}
            />
            <div className="cart-more__body">
              <p className="cart-more__name">
                <VegMark veg={item.is_veg} />
                <span>{item.name}</span>
              </p>
              <p className="cart-more__price money">{money(item.price)}</p>
            </div>
            <Button
              aria-label={`Add ${item.name}`}
              onClick={() => addItem(item)}
              size="icon"
              variant="outline"
            >
              <Plus />
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
