/**
 * The one control that decides whose marketing a screen is showing.
 *
 * Renders nothing for an OWNER, who has exactly one restaurant and may not
 * name it — `resolve_insights_scope` refuses a `restaurant_id` from them.
 */

import { Megaphone } from 'lucide-react';
import type { MarketingScope } from '../../hooks/useMarketingScope';

export function RestaurantScopePicker({ scope }: { scope: MarketingScope }) {
  if (!scope.isAdmin) {
    return null;
  }
  return (
    <label className="hub-scope">
      <span className="hub-scope__label">Restaurant</span>
      <select
        aria-label="Restaurant"
        className="hub-scope__select"
        onChange={(event) => scope.setSelectedRestaurantId(event.target.value)}
        value={scope.selectedRestaurantId}
      >
        <option value="">Select a restaurant…</option>
        {scope.restaurants.map((restaurant) => (
          <option key={restaurant.id} value={restaurant.id}>
            {restaurant.name}
          </option>
        ))}
      </select>
    </label>
  );
}

/**
 * The honest screen for an admin who has not chosen yet.
 *
 * Asking is the point. Fetching anyway renders the backend's 400 as a
 * failure, which reads as "this feature is broken" rather than "pick a
 * restaurant" — the exact mistake this component exists to stop repeating.
 */
export function RestaurantScopePrompt({
  scope,
  what,
}: {
  scope: MarketingScope;
  /** What belongs to the restaurant, in the owner's words. */
  what: string;
}) {
  return (
    <div className="mkt-hub">
      <section className="hub-card">
        <div className="hub-state">
          <span className="hub-state__icon">
            <Megaphone size={24} strokeWidth={2} />
          </span>
          <strong>Whose marketing?</strong>
          <p>
            {scope.restaurants.length > 0
              ? `${what} belong to one restaurant. Choose which.`
              : 'No restaurants are available on this account yet.'}
          </p>
          <RestaurantScopePicker scope={scope} />
        </div>
      </section>
    </div>
  );
}
