import { Link } from "@tanstack/react-router";
import { ArrowRight, Plus } from "lucide-react";

import { DishImage } from "@/components/bangkok/dish-image";
import { VegMark } from "@/components/bangkok/veg-mark";
import { Button } from "@/components/ui/button";
import type { MenuItem } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
import { useMenuItems } from "@/lib/queries";
import { useMoney, useStorefrontCopy } from "@/lib/storefront";

/** Six fills two rows of three without becoming a second menu. */
const PICKS = 6;

/**
 * Real dishes, with their prices, on the page that was only describing them.
 *
 * Everything above this block tells somebody who this restaurant is. Nothing
 * on it told them what anything costs — so the question a first-time customer
 * actually has, "is this a forty-rupee shop or a four-hundred-rupee one",
 * could only be answered by leaving for the menu. A landing page for a
 * business that sells food should be able to sell food.
 *
 * The dishes are the kitchen's own bestsellers where it has marked any, and
 * otherwise simply the first things on its menu. No scoring and no
 * personalisation: this block is read by people who have never ordered here,
 * for whom a "recommended for you" would be a claim about a stranger.
 *
 * It shares the menu page's query, so arriving here warms the menu and
 * arriving from the menu costs nothing.
 *
 * Only dishes that can be added in one tap appear. A pick that opens a size
 * chooser is a shop window you cannot buy from, and a silent default is the
 * trick this codebase refuses everywhere else.
 */
export function BrandPicks() {
  const money = useMoney();
  const copy = useStorefrontCopy();
  const { addItem, cart, restaurantId, branchId } = useBangkokStore();
  const menuQuery = useMenuItems(restaurantId, branchId || undefined);

  const inCart = new Set(cart.map((line) => line.itemId));
  const sellable = (menuQuery.data ?? []).filter(
    (item) => item.is_available && !item.has_sizes && !item.has_customizations,
  );

  const picks: MenuItem[] = [
    ...sellable.filter((item) => item.is_bestseller),
    ...sellable.filter((item) => !item.is_bestseller),
  ].slice(0, PICKS);

  if (picks.length === 0) return null;

  return (
    <section className="picks">
      <div className="page-pad section-pad picks__inner">
        <header className="picks__head">
          <div>
            <p className="eyebrow">Straight from the counter</p>
            <h2 className="font-display picks__title">What people order at {copy.name}</h2>
          </div>
          <Link className="picks__all" to="/menu">
            See all dishes <ArrowRight aria-hidden="true" />
          </Link>
        </header>

        <ul className="picks__grid">
          {picks.map((item) => (
            <li className="picks__card" key={item.id}>
              <Link
                aria-label={item.name}
                className="picks__shot"
                params={{ itemId: item.id }}
                to="/menu/$itemId"
              >
                <DishImage
                  category={item.category}
                  name={item.name}
                  src={item.image_url}
                />
              </Link>

              <div className="picks__body">
                <p className="picks__name">
                  <VegMark veg={item.is_veg} />
                  <Link params={{ itemId: item.id }} to="/menu/$itemId">
                    {item.name}
                  </Link>
                </p>
                {item.description?.trim() && (
                  <p className="picks__desc">{item.description}</p>
                )}
                <div className="picks__foot">
                  <span className="picks__price money">{money(item.price)}</span>
                  <Button
                    aria-label={`Add ${item.name}`}
                    onClick={() => addItem(item)}
                    size="sm"
                    variant={inCart.has(item.id) ? "secondary" : "default"}
                  >
                    <Plus />
                    {inCart.has(item.id) ? "Added" : "Add"}
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
