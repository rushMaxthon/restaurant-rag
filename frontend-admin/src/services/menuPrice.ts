import type { UserRole } from "../types/app";

type Priced = { price: number | string; base_price?: number | string | null };

/**
 * The price to show for a dish in this panel's menu list.
 *
 * `price` is what the customer pays: what the owner typed, plus the
 * platform's commission. `base_price` is what the owner typed.
 *
 * An owner is shown the figure they typed. Their editor already loads it, so
 * a list showing 55 beside an editor showing 50 was the commission rate
 * written out as a subtraction - on the screen of somebody the rate is
 * deliberately not shown to. The platform admin is shown the listed price,
 * which is the one a customer would quote back to them.
 *
 * Falls back to `price` where no typed figure was kept: the two are then the
 * same number, and nothing has yet needed to tell them apart.
 */
export function menuListPrice(item: Priced, role: UserRole | null): number | string {
  if (role === "ADMIN") return item.price;
  return item.base_price ?? item.price;
}
