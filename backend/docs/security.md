# Security rules

What the 2026-10-07 security review found, what was changed, and the rules
that keep it fixed. Each rule names the file that holds it and the test that
fails if it is broken.

## A deployment that forgets a setting is safe, not open

- `environment` defaults to `production` and `debug` to `False`
  (`config/settings.py`). Local development sets `ENVIRONMENT=development` in
  `.env`. They used to default to development values, so a deployment that
  forgot them accepted the fixed phone code `123456` for **any** customer and
  even returned it in the response.
- Outside local development the API and the Celery worker **refuse to start**
  when `JWT_SECRET_KEY` is the repository default or shorter than 32
  characters, or `DEBUG` is on (`config/safety.py`, `test_config_safety`).
- `/docs`, `/redoc` and `/openapi.json` are served locally only.
- `docker-compose.yml` defaults `ENVIRONMENT` to `production`.

## Every attempt is counted

`services/rate_limit.py` (`test_rate_limit`): a fixed window in Redis, shared
by every worker, answered with 429 and `Retry-After`. If Redis is down the
request is allowed.

| What | Per IP | Per account / globally |
|---|---|---|
| Login | 20 / min | 10 per account / 15 min |
| Register | 10 / hour | |
| Phone code request | 10 / hour | 5 per number / hour |
| Phone code check | 20 / 10 min | 10 per number / 15 min |
| Print-agent pairing | 10 / 10 min | 60 / 10 min across everyone |
| Chat message and stream | 30 / min | |
| Chat place-order | 20 / min | |
| Address suggest / resolve | 60 / 30 per min | |
| Delivery quote | 30 / min | |

The IP is the **last** `X-Forwarded-For` entry (what Render's proxy
recorded), never the first, which the caller writes. The traffic counter uses
the same function.

## Every response says how a browser may treat it

- API: `middleware/security_headers.py` (`test_security_headers`) - nosniff,
  no framing, `default-src 'none'`, no referrer, HSTS outside local, and
  `Cache-Control: no-store` on any request that carried a login.
- Storefront, admin and kitchen: `vercel.json` in each app - no framing
  (clickjacking), no plugins, no `<base>` hijacking, nosniff, HSTS.
- Not done yet, on purpose: a full CSP script allowlist. Stripe and Razorpay
  load from several hosts; try it as `Content-Security-Policy-Report-Only`
  first.

## Text an owner types is never markup

Structured data in a `<script>` tag goes through `jsonLd()`
(`frontend-customer/src/lib/json-ld.ts`), never `JSON.stringify` - a `</script>`
in an FAQ answer ran as script for every visitor. Image links must be
`https://` or a site path (`schemas/common.py`, `test_image_urls`).

## Money and permissions

- The welcome discount is for a first order: any real order counts, COD and
  unpaid checkouts included; only a checkout cancelled for a failed payment
  does not (`personalized_offers._latest_order_at`, `test_welcome_offer_once`).
- `platform_fee` is admin-only, like `commission_percent`
  (`test_platform_fee_admin_only`).
- An owner cannot change a customer's phone - it is a login
  (`test_owner_cannot_change_customer_phone`).
- `/chat/place-order` refuses a conversation that belongs to another
  customer, with a 404 (`test_chat_order_session_owner`).

## Data each viewer gets

- A KITCHEN account gets no customer email, account phone, payment reference
  or refund error (`OrderResponse.for_viewer`,
  `test_kitchen_sees_no_customer_account`). It keeps the order's contact name
  and phone.
- `GET /orders` returns at most 200, also when no limit is sent.
  `GET /admin/ai-logs` reads the last 30 days (up to 365), not the table.
- Public restaurant routes do not return `owner_id`.

## Secrets at rest and in logs

- Marketing channel credentials are encrypted (`connections.seal_credentials`,
  `test_channel_credentials_encrypted`), like gateway keys and bank numbers.
  Older plaintext rows still read and are encrypted on their next save.
  `SECRETS_ENCRYPTION_KEY` must be set (declared in `render.yaml`).
- Logs carry a phone as its last four digits, a device token as its last
  eight characters, and what a customer typed as its length and a
  fingerprint outside local development (`services/log_privacy.py`,
  `test_log_privacy`).

## Calling out, and being called

- A URL the server will call (the SMS gateway) must be public `https`, checked
  when saved and again before each send, and its reply is never shown back
  (`services/outbound_url.py`, `test_outbound_url`).
- The delivery webhook keeps a tracking link only when it points at Pidge's
  own tracking host, and compares its secret in constant time
  (`test_delivery_webhook_tracking_link`).
- Razorpay webhooks de-duplicate on the signed body, not the unsigned
  `X-Razorpay-Event-Id` header, so a replay cannot re-run transfers.
- Gateway and internal error text stays in the log; customers and staff get
  a fixed sentence.

## Row-level security

Migration `0088` switches RLS on for the tables older migrations left open,
so a database built from scratch starts closed. The live Supabase project
already had it on every table.

## Closed in the follow-up (same day)

- **Script allowlist, report-only.** Each `vercel.json` sends
  `Content-Security-Policy-Report-Only`; browsers report what it would block
  to `POST /api/security/csp-report` (`api/security_reports.py`,
  `test_csp_report`), which logs it with query strings stripped. The admin's
  one inline script is allowed by hash, kept in step by `src/cspHash.test.ts`.
  Switch the header to enforcing once the logs show no reports from
  legitimate pages. The storefront still needs `'unsafe-inline'` for its
  server-rendered scripts until they carry nonces.
- **Admin and owner logins last 8 hours** (`jwt_staff_token_expire_minutes`,
  `test_staff_token_lifetime`); kitchen tablets and customers keep 24.
- **The Users list is paged on the server** (`search`, `role`, `status`,
  `limit` 50 by default and at most 200, `offset`, `X-Total-Count`), and its
  tiles come from `GET /admin/users/stats` (`test_admin_users_paging`).
- **Print-agent pairing codes live in Redis**, redeemed with GET and DELETE in
  one transaction so a code works once across every worker
  (`test_print_pairing_codes`).
- **Login costs the same for an unknown account** - one bcrypt check against
  a dummy hash (`test_login_timing`).
- **An owner can only read their own AI offer run's result**
  (`test_owner_task_status_scope`).
- **Android release builds can be signed with a real key**: put it in
  `android/keystore.properties` (see the `.example`) or `RELEASE_STORE_*`
  environment variables. Without one a release still builds on the debug key,
  with a warning that it must not be distributed.

## Still open, on purpose

- **Login tokens in browser storage.** Moving them to httpOnly cookies needs
  the API and the sites on one domain of your own (api.example.com and
  example.com); with onrender.com and vercel.app the cookie is third-party
  and browsers block it. Decided 2026-10-07: do it once that domain exists.
- **Registration says when an email or phone is taken.** Hiding it would leave
  a customer who already has an account with no idea why sign-up "worked" and
  nothing happened. It is rate limited (10 sign-ups per hour per address)
  instead.
- **Outside the code:** create the Android release key and keep it safe;
  restrict the Firebase API keys to the app ids in Google Cloud; set
  `SECRETS_ENCRYPTION_KEY` on Render.
