/**
 * Which restaurant a tenant-scoped screen reads, for an admin.
 *
 * There are two places an admin can say: the sidebar switcher, which scopes
 * the whole panel, and the picker these screens grew because the API refuses
 * an admin who names nobody. They were independent, so they could disagree —
 * and the screen silently believed its own.
 *
 * The sidebar wins whenever it names a restaurant: it is the one the admin
 * can see on every screen. The page's own pick only stands in while the
 * sidebar says "All restaurants", which these screens cannot honour.
 *
 * Pure, and here rather than inside the hook, so the rule can be tested
 * without rendering anything.
 */
export function scopedRestaurant(
  activeRestaurantId: string | null,
  pickedRestaurantId: string,
): string {
  return activeRestaurantId || pickedRestaurantId;
}
