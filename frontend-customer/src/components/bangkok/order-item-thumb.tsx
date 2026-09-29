import { useMenuItem } from "@/lib/queries";
import { DishImage } from "./dish-image";

/** Order line items only carry a name snapshot, not an image — this resolves
 * the live menu item (if it still exists) to reuse the same photo/placeholder
 * treatment dishes get on the menu, so an order looks like the same app. */
export function OrderItemThumb({
  menuItemId,
  name,
  className,
}: {
  menuItemId: string;
  name: string;
  className?: string;
}) {
  const item = useMenuItem(menuItemId);
  return <DishImage src={item.data?.image_url ?? null} name={name} className={className ?? ""} />;
}
