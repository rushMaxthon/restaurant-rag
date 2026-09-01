import type { UserPreferences } from '../types/app';

/**
 * Stable string identity for a preference set.
 *
 * The store replaces the `preferences` object whenever it merges the remote
 * copy or syncs a profile, even when nothing the user chose actually changed.
 * Effects that fetch preference-ranked data must key on this string instead of
 * the object, or every replacement re-fires their requests.
 *
 * Ported from `mobile/src/utils/preferencesKey.ts`, which exists for the same
 * reason.
 */
export function buildPreferencesKey(
  preferences: UserPreferences | null | undefined,
): string {
  if (!preferences) {
    return 'none';
  }
  return JSON.stringify({
    cuisines: [...(preferences.cuisines ?? [])].sort(),
    favoriteItems: [...(preferences.favorite_items ?? [])].sort(),
    diet: preferences.diet ?? null,
    spiceLevel: preferences.spice_level ?? null,
    budget: preferences.budget ?? null,
    updatedAt: preferences.updated_at ?? null,
  });
}
