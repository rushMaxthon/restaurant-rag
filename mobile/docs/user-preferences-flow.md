# User Preferences Personalization Flow

This document explains how personalization currently works in the mobile app across:

- first install onboarding
- guest users
- login and guest-to-authenticated sync
- logged-in recommendations
- restaurant menu ordering
- profile preference updates
- fallback behavior

It is intended as a developer reference for the mobile app in `mobile/`.

## Related Files

- `src/store/AppStore.tsx`
- `src/services/storage.ts`
- `src/services/api.ts`
- `src/screens/home/HomeScreen.tsx`
- `src/screens/restaurant/RestaurantScreen.tsx`
- `src/screens/profile/preferences/PreferencesOnboardingScreen.tsx`
- `src/screens/profile/preferences/PreferencesScreen.tsx`
- `src/utils/menuPersonalization.ts`

## High-Level Flow

```text
First app launch
  -> preferences onboarding
  -> save selections locally
  -> home uses those selections immediately

Guest session
  -> preferences live in AsyncStorage
  -> home recommendations use local preference context
  -> restaurant menus reprioritize locally from recommendation scores

Login
  -> local preferences sync to backend
  -> backend stores preferences in user_preferences
  -> backend becomes the long-term source of truth

Logged-in session
  -> recommendations use stored preferences + history-based signals
  -> users may also receive separate generated offer cards created from reusable templates
  -> restaurant menus reprioritize from recommendation output
  -> profile updates refresh future ranking
```

## 1. First App Install Flow

On a fresh install, the app checks local boot data during `AppStore` bootstrap.

What happens:

1. No saved auth session is found.
2. No saved preferences are found.
3. The preferences onboarding flow is shown.
4. The user selects cuisines, diet, spice level, budget, and optional favorite items.
5. The app saves those selections to AsyncStorage.
6. The onboarding flag is also saved locally so the app does not show the same wizard every launch.
7. The Home screen then loads recommendations using the saved local preference context.

Important behavior:

- The app does not require login to start personalizing.
- Local preferences are available immediately after onboarding.
- Home does not wait for account creation to start showing preference-aware picks.

## 2. Guest User Flow

If the user is not logged in:

- preferences come from AsyncStorage
- the app treats those preferences as the active profile
- Personalized Picks uses those local preferences as ranking context
- restaurant menus are reprioritized using recommendation scores
- no guest preference record is saved to the backend database
- no authenticated preferences API call is made

Important clarification:

- Guest preferences are not persisted to backend user storage.
- The app may still call the public recommendation query endpoint with the local preference payload so the backend can rank results for that session.
- That is recommendation context, not account-level preference persistence.

### Guest Flow Example

If a guest selects:

- `Pizza`
- `Italian`
- `VEG`

Then the expected behavior is:

- pizza-related items should rank higher in Personalized Picks
- Italian restaurants and Italian dishes should be prioritized more often
- veg-friendly items should outrank non-veg items when the recommendation score is close
- inside a restaurant, pizza and related Italian items should float closer to the top when recommendation results include them

## 3. Login Flow

When a guest logs in or registers:

1. The auth session is stored locally.
2. Existing local preferences are kept in memory.
3. If local preferences already exist, the app sends them to the backend with `PUT /api/preferences/me`.
4. The backend saves them in `user_preferences`.
5. The API response becomes the synced preference state in the app.

Why this matters:

- guest setup is not lost after login
- the backend now has a durable copy of the user’s taste profile
- recommendations can combine preference data with long-term account signals

Backend source of truth after login:

- For long-term personalization, the backend becomes the canonical store.
- The app still keeps a local cached copy for startup speed and resilience.
- On future launches, the app hydrates local preferences first and then silently refreshes from the backend.

## 4. Logged-In User Flow

For authenticated customers, Home screen Personalized Picks is driven by a combination of:

- stored user preferences
- local preference updates that have just been synced
- order history
- popularity
- popularity
- budget fit
- novelty

In practice:

- Home first tries authenticated recommendation paths
- Home can also show a separate `Offers` strip for live restaurant and branch campaigns
- if useful results come back, those are used
- if the authenticated result is empty or temporarily fails, the app degrades gracefully instead of leaving Home empty

Important distinction:

- `Personalized Picks` is recommendation ranking
- `Offers` is a separate generated-offer system built from business-configured templates and rules
- both can coexist on Home without replacing each other

Restaurant menus also adapt:

- the restaurant screen loads menu items
- it also loads recommendation rows for the current user context
- recommendation rows are filtered to the current restaurant
- `sortMenuItemsByRecommendationSignal()` reorders the menu

Current menu tie-break order after recommendation score:

1. recommendation score
2. dynamic branch bestseller flag
3. popularity score
4. popularity
5. category
6. item name

## 5. Profile -> User Preferences

When a logged-in user opens Profile -> User Preferences and changes selections:

1. The screen updates local preference state.
2. The app sends the normalized payload to `PUT /api/preferences/me`.
3. The backend updates or creates the `user_preferences` row.
4. The synced response is stored back in app state.
5. Future Home recommendation fetches use the updated preference profile.
6. Restaurant menu reprioritization also changes because menu ranking reads from the same recommendation context.

Expected result:

- Personalized Picks refreshes toward the new taste profile
- restaurant menus reorder accordingly
- the backend remembers the new profile for future sessions

This update path must not break:

- onboarding preferences
- guest-only local preferences
- recommendation fallback behavior

## 6. Example Scenarios

### Example 1: Explicit Preference Dominance

Initial state:

- user selects `Pizza`
- user selects `Italian`
- user selects `VEG`

Expected ranking behavior:

- pizza-heavy items rank higher
- Italian cuisine gets a strong boost
- veg items gain preference alignment

### Example 2: Behavior Adapts Over Time

Initial state:

- user starts with Pizza-focused preferences

Later:

- user repeatedly orders Burgers

Expected outcome:

- burger-related items should gradually climb higher
- burger-friendly restaurants may surface more often
- personalization becomes less dependent on the original explicit preference alone

This is the intended adaptive behavior for logged-in users.

### Example 3: Profile Update Override

Initial state:

- user originally selected `Pizza`

Later in Profile:

- user changes cuisines to `Sushi`

Expected outcome:

- future recommendation ranking should shift toward Sushi-related items
- restaurant menu reprioritization should follow the new recommendation output

## 7. Fallback Logic

Home should never feel broken or empty.

If the app has:

- no saved preferences
- no backend preference row
- no meaningful order history
- a temporary recommendation API failure

Then fallback behavior should still produce useful content:

- top-rated items
- popular items
- general public recommendation results

Current UX goals:

- Personalized Picks section should stay visible
- recommendation failure should degrade gracefully
- restaurant and Home discovery should remain usable

## 8. Important Technical Notes

### AsyncStorage Usage

Guest and cached preference state is stored locally in AsyncStorage.

Relevant persisted keys include:

- `restaurant-rag-mobile-preferences`
- `restaurant-rag-mobile-preferences-onboarding`

This allows:

- first-launch onboarding persistence
- guest personalization across app restarts
- fast startup before backend refresh completes

### Backend DB Usage

For logged-in users, preferences are stored in the backend `user_preferences` table.

Important fields include:

- `favorite_cuisines`
- `dietary_preferences`
- `spice_level`
- `budget_tier`
- `favorite_items`
- historical scoring fields such as `cuisine_affinity_scores`

### Guest -> Logged-In Sync

Current sync behavior:

1. guest chooses preferences locally
2. user logs in
3. app sends local preferences to `PUT /api/preferences/me`
4. backend stores them
5. synced backend response replaces or confirms the local profile

### Recommendation Request Priority

At a high level, the mobile API layer prefers:

1. authenticated recommendation query with local preference context when available
2. authenticated recommendations endpoint
3. authenticated query fallback
4. guest/public query with local preferences
5. generic public fallback query with no preference payload

This design gives:

- best personalization for signed-in users
- usable guest personalization
- resilient fallback when any one path fails

### Current Limitation

Adaptive behavior is strongest for:

- explicit preferences
- order history
- popularity signals

The system does not currently persist a dedicated backend signal for lightweight non-order interactions such as:

- simple taps
- passive views
- add-to-cart attempts without completed order history

Those signals may still influence immediate UI state indirectly, but they are not yet a durable recommendation input in the backend model.

## Developer Summary

If you need to reason about personalization in the mobile app, use this mental model:

- guests personalize locally
- authenticated users personalize locally first, then sync to backend
- Home recommendations are always allowed to fall back instead of failing hard
- restaurant menu ordering is downstream of recommendation ranking
- profile preference edits should affect both Home and menu ordering
- long-term recommendation quality improves most when explicit preferences and completed order history are both available
