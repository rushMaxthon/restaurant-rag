# Per-App User Identity

Customer accounts belong to exactly one app. The same person signing up in the
Marketplace app and in the Bangkok Bowl app has **two separate accounts**, each
with its own orders, favorites, preferences and chat history.

Platform staff (`ADMIN`, `OWNER`) belong to no app and sign in through the admin
panel as before.

## The rule

| Role | `users.app_client_id` | Uniqueness |
| --- | --- | --- |
| `CUSTOMER` | required | email and phone unique **per app client** |
| `ADMIN` / `OWNER` | must be `NULL` | email and phone unique **platform-wide** |

Enforced by the database, not just by application code:

- `ck_users_app_client_scope_matches_role` — the CHECK behind the table above
- `uq_users_app_client_id_email_customer` — `(app_client_id, lower(email)) WHERE role='CUSTOMER'`
- `uq_users_app_client_id_phone_number_customer` — same for phone
- `uq_users_email_platform` / `uq_users_phone_number_platform` — global, staff only
- `uq_users_id_app_client_id` — target of the composite foreign keys on user-owned tables

Because emails are indexed on `lower(email)`, they are compared
case-insensitively. A customer *may* reuse a staff email; the partial indexes
allow it deliberately, so registration does not check staff rows.

## Which app is "this request"?

Identity resolution is separate from restaurant scoping and lives in
`resolve_identity_app_client_id()` (`app/services/app_clients.py`):

| Caller | `X-App-Bundle-Id` | Identity scope |
| --- | --- | --- |
| Marketplace mobile | `com.quickbite.all` | `marketplace` |
| Bangkok Bowl mobile | `com.quickbite.bangkokbowl` | `bangkok_bowl` |
| Customer web | *(none)* | `marketplace` (the default client) |
| Admin panel | *(none)* | n/a — staff tokens carry no app |

Restaurant scoping **fails open** to the whole marketplace when the header is
missing, which is fine for browsing. Identity must not: a caller without a
resolvable bundle id is treated as the default marketplace client, so stripping
the header cannot move an account between apps. If no marketplace client exists
at all, auth returns **503** rather than guessing.

The default client is `settings.default_app_client_key` (`marketplace`), falling
back to the oldest active `MARKETPLACE` client.

## Tokens

`create_access_token` emits:

```json
{ "sub": "...", "role": "CUSTOMER", "exp": ..., "iat": ...,
  "app_client_id": "...", "token_version": 0 }
```

`app_client_id` is `null` for staff. The app *key* and bundle id are
deliberately **not** claims — both are editable from the admin panel, and a
mutable authorization claim is a bug waiting to happen.

`_get_user_from_token` rejects a token when:

1. `token_version` is missing or no longer matches `users.token_version`
2. the `app_client_id` claim is absent entirely (issued before this feature)
3. the claim is `null` but the user is app-scoped, or is a customer
4. the claim does not match both the user's app **and** the app making the request

So a Bangkok Bowl token returns **401** in the Marketplace app, and vice versa.
On endpoints that allow guests, a cross-app token degrades to anonymous rather
than erroring; the mismatch is logged.

## Signing out everywhere

`POST /api/auth/logout-all` bumps `users.token_version`, invalidating every
token issued to that account — including the one making the call. Only that
account is affected; the same person's accounts in other apps are different
users and keep their sessions.

Use it after a password change, or bump the column directly to force a global
re-login:

```sql
UPDATE users SET token_version = token_version + 1;
```

## Mobile

The app stores `appClientId` / `appKey` alongside the token. At startup, if the
resolved app config reports a different app client than the stored session, that
session is discarded locally instead of waiting for the backend to 401 every
request — which is what happens when a build's bundle id changes.

Sessions saved by older builds have no stored identity; they are simply
re-verified against the backend on the next request.

## Migrating an existing deployment

Existing customers were assigned to the `marketplace` client, so all of their
history stays visible in the marketplace app and on the web exactly as before.
A customer who wants a branded app signs up there separately.

Deploying the token changes signs everyone out once. Mobile self-heals: startup
calls `getUserPreferences` with the stored token, gets a 401, and clears the
session, so users land on the login screen rather than on broken screens.
There is no 401 interceptor, so a token invalidated *mid-session* surfaces as a
generic error toast until the app is relaunched — prefer deploying at low traffic.
