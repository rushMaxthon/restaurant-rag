import { Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { DishImage } from "./dish-image";

import { useBangkokStore } from "@/lib/bangkok-store";
import { useAuth } from "@/lib/auth";
import { useFavorites, useGeneratedCombos } from "@/lib/queries";
import { useMoney } from "@/lib/storefront";

/**
 * Two short strips above the menu: what you always order, and what other
 * people order together.
 *
 * Neither is a grid. The menu below is the grid, and a second one above it
 * would just be a longer menu. These are one row each, scrolled sideways, and
 * they disappear entirely when there is nothing to put in them.
 */

/**
 * A dish you keep coming back to.
 *
 * A favourite in a food app is not a wishlist entry to admire later, it is
 * "my usual" — so the affordance here is ordering it, not opening it. Dishes
 * that need a size or toppings chosen still go to their page, because adding a
 * silent default and surprising someone at checkout is the bug this app has
 * fixed twice already.
 */
function Usual({
  item,
}: {
  item: { id: string; name: string; price: string | number; image_url?: string | null };
}) {
  // Prices in whatever this restaurant charges in.
  const money = useMoney();
  const { addItem, conflictsWithCart } = useBangkokStore();
  const menuItem = item as never;
  const needsChoices =
    (item as { has_sizes?: boolean }).has_sizes ||
    (item as { has_customizations?: boolean }).has_customizations;
  const conflicts = conflictsWithCart(menuItem);

  if (needsChoices || conflicts) {
    return (
      <Link to="/menu/$itemId" params={{ itemId: item.id }} className="usual">
        <DishImage src={item.image_url ?? null} name={item.name} className="usual__photo" />
        <span className="usual__name">{item.name}</span>
        <span className="usual__price money">{money(item.price)}</span>
      </Link>
    );
  }

  return (
    <div className="usual">
      <Link to="/menu/$itemId" params={{ itemId: item.id }} className="usual__open">
        <DishImage src={item.image_url ?? null} name={item.name} className="usual__photo" />
        <span className="usual__name">{item.name}</span>
      </Link>
      <button
        type="button"
        className="usual__add"
        onClick={() => addItem(menuItem)}
        aria-label={`Add ${item.name} to your order`}
      >
        <Plus className="size-3.5" />
        {money(item.price)}
      </button>
    </div>
  );
}

/**
 * Two dishes people actually ordered together.
 *
 * The headline is how many people did it, not the discount. These combos are
 * derived from real orders rather than written by a marketer, which is the
 * genuinely interesting thing about them and the one thing a "SAVE $3.50"
 * badge would throw away. The saving is still there, underneath, where a
 * price belongs.
 */
function Pair({
  combo,
}: {
  combo: {
    id: string;
    combo_name: string;
    items: { menu_item_id: string; name: string; image_url?: string | null }[];
    unique_user_count: number;
    suggested_combo_price: string | number;
    savings_amount: string | number;
  };
}) {
  // Prices in whatever this restaurant charges in.
  const money = useMoney();
  const saving = Number(combo.savings_amount || 0);
  const people = combo.unique_user_count;

  return (
    <article className="pair">
      <div className="pair__plates">
        {combo.items.slice(0, 3).map((item, index) => (
          <Link
            to="/menu/$itemId"
            params={{ itemId: item.menu_item_id }}
            className="pair__plate"
            style={{ zIndex: 3 - index }}
            key={item.menu_item_id}
            aria-label={item.name}
          >
            <DishImage src={item.image_url ?? null} name={item.name} className="pair__photo" />
          </Link>
        ))}
      </div>
      <p className="pair__what">{combo.items.map((item) => item.name).join(" + ")}</p>
      <p className="pair__who">
        {people === 1 ? "Someone ordered" : `${people} people ordered`} these together
      </p>
      <p className="pair__price">
        <span className="money">{money(combo.suggested_combo_price)}</span>
        {saving > 0 && (
          <span className="pair__saving">{money(saving)} less than separately</span>
        )}
      </p>
    </article>
  );
}

export function UsualsAndPairs() {
  const { isAuthenticated } = useAuth();
  const favorites = useFavorites(isAuthenticated);
  const { restaurantId } = useBangkokStore();
  const combos = useGeneratedCombos(restaurantId, 8);

  const usuals = favorites.data ?? [];
  const pairs = (combos.data ?? []).filter((combo) => (combo.items?.length ?? 0) > 1);

  if (usuals.length === 0 && pairs.length === 0) return null;

  return (
    <>
      {usuals.length > 0 && (
        <section className="strip" aria-labelledby="usuals-heading">
          <h2 className="strip__heading" id="usuals-heading">
            What you always order
          </h2>
          <div className="strip__rail">
            {usuals.slice(0, 10).map((item) => (
              <Usual item={item} key={item.id} />
            ))}
          </div>
        </section>
      )}

      {pairs.length > 0 && (
        <section className="strip" aria-labelledby="pairs-heading">
          <h2 className="strip__heading" id="pairs-heading">
            Ordered together
          </h2>
          <div className="strip__rail">
            {pairs.slice(0, 8).map((combo) => (
              <Pair combo={combo} key={combo.id} />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
