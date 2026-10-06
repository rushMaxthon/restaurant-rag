# Restaurant payouts through Razorpay Route — design

Date: 2026-10-05. Status: approved 2026-10-06; amended the same day with
"Collecting on the platform's account" after reading the payment code.

## Why

Customers of six of the seven real restaurants pay into the **platform's**
Razorpay account, and nothing sends the restaurant its share. The seventh
(Bhagwati Bakery) uses its own Razorpay keys, so its money arrives at the
restaurant and the platform's commission and delivery fee sit in the wrong
account. Both are fixed by paying every restaurant through the platform's
Razorpay account with **Razorpay Route**: each restaurant is a linked account,
each paid order transfers the restaurant's share, and Razorpay settles it to
the restaurant's bank.

## Decisions (made by the owner of the platform)

| Question | Decision |
|---|---|
| How money moves | Razorpay Route: linked account per restaurant, one transfer per order |
| Razorpay's fee (~2% + GST) | **The platform pays it.** The restaurant's share is never reduced by it |
| Discounts (offers, promo codes) | **Out of the restaurant's share.** Owners create them for their own restaurant |
| When the share is released | **On delivery** (or collection, for pickup). Created on payment, on hold until then |
| Restaurants on their own keys | **Everyone moves to Route.** Own keys can be switched off per restaurant once its linked account is active |

## The split

For one paid online order, from the columns already on `orders`:

```
restaurant_share = subtotal - commission_amount - discount_amount
                 + packaging_fee + food_tax_amount
platform_keeps   = commission_amount + delivery_fee + delivery_tax_amount
                 + platform_fee
```

`restaurant_share + platform_keeps` must equal `total_amount` to the paisa.
If it does not, no transfer is made, the ledger row is marked `BLOCKED` with
the difference, and the admin sees it. Never transfer a figure that does not
reconcile.

`commission_amount` NULL (orders from before commission was recorded) means
commission 0. A share below zero (a discount larger than the food) is
`BLOCKED` the same way. The function is pure (`services/payouts/split.py`) and
is the only place this arithmetic lives.

Out of scope: COD orders (the restaurant already holds that cash), Stripe
orders, and orders whose payment settled into a restaurant's own keys (they
show as "paid directly" in the ledger, never transferred).

## Collecting on the platform's account (found while planning)

The opening of this spec assumed six restaurants already pay into the
platform's Razorpay account. They do not: `payments/registry.py` has no
platform Razorpay fallback at all (`platform_provider_for` is Stripe only),
so a restaurant without its own keys is simply not offered Razorpay. Only
Bhagwati has ever taken a Razorpay payment. So Route needs the collecting
half too:

- **The platform's Razorpay account takes a restaurant's payment only when
  it can pay that restaurant out**: payouts switched on, the platform keys
  configured (not the `rzp_test_mock` default), the restaurant's linked
  account `ACTIVE`, and no enabled Razorpay keys of its own. Anything less
  and money would land with the platform with no way to pass it on.
  `payments_require_restaurant_account` does not apply to this path: that
  setting guards against the platform silently keeping a restaurant's
  money, which Route is the opposite of.
- **Each payment remembers which account took it**:
  `payment_transactions.on_platform_account`. Confirming, reconciling and
  cancelling an attempt use that account, not whatever the restaurant is set
  to now, so switching Bhagwati onto Route cannot strand its earlier orders.
- **The browser's confirmation records the payment id** (`pay_…`). It did
  not, and a transfer is made from a payment id.
- **A platform webhook**: `POST /api/payments/razorpay/webhook`, verified
  with `RAZORPAY_WEBHOOK_SECRET`. It carries payment, refund, transfer,
  settlement and linked-account events.
- **"Collect through the platform" for Bhagwati is the existing switch** on
  its own Razorpay keys: turn them off once its linked account is ACTIVE.
  No new control.

Onboarding also needs a registered address and a business category
(Razorpay asks for both on account creation), so the linked-account row
carries `street`, `city`, `state`, `postal_code` as well.

## Linked accounts — `restaurant_payout_accounts`

One row per restaurant:

- `razorpay_account_id` (`acc_…`), `product_id`, `stakeholder_id`
- `status`: `DRAFT` → `SUBMITTED` → `UNDER_REVIEW` / `NEEDS_CLARIFICATION`
  → `ACTIVE`, or `SUSPENDED` — mirrored from Razorpay's activation status
- `legal_business_name`, `business_type`, `pan`, `contact_name`, `email`,
  `phone`
- `bank_account_number_encrypted`, `bank_account_last4`, `ifsc`,
  `beneficiary_name` — encrypted with `services/secrets.py` like gateway keys;
  only the last four digits are ever returned
- `last_error`, `requirements` (what Razorpay still asks for), timestamps,
  `updated_by_user_id`
- RLS enabled in the migration (CLAUDE.md: every new table)

Onboarding, server side, through Razorpay's v2 Accounts API: create account
(`type: route`, PAN, profile), create stakeholder, request the `route`
product, then submit the settlement bank account on the product. The exact
calls are verified against Razorpay test mode while building; the ones in
the docs today are `POST /v2/accounts`, `POST /v2/accounts/:id/stakeholders`,
`POST /v2/accounts/:id/products`, `PATCH /v2/accounts/:id/products/:pid`.
Status is refreshed by webhook (`account.*`, `product.route.*`) and by a
"Refresh status" button — never assumed.

Only the platform admin creates or edits a linked account. The owner sees
their own status read-only, with what Razorpay still needs.

## The ledger — `restaurant_payouts`

One row per order (unique on `order_id`):

- `restaurant_id`, `order_id`, `payment_id` (Razorpay `pay_…`)
- `restaurant_share`, `platform_keeps`, `currency`
- `status`: `WAITING_ACCOUNT` (no active linked account yet), `HELD`
  (transfer created, on hold), `RELEASED`, `SETTLED`, `REVERSED`, `FAILED`,
  `BLOCKED` (split did not reconcile), `NOT_APPLICABLE` (COD / own keys)
- `transfer_id` (`trf_…`), `settlement_id`, `released_at`, `settled_at`,
  `reversed_at`, `last_error`, `attempts`, timestamps
- RLS enabled in the migration

## The flow

1. **Payment confirmed** (existing webhook / verify path) → `record_payment`:
   compute the split, write the ledger row. If the restaurant's linked account
   is `ACTIVE` and payouts are enabled → `POST /v1/payments/:id/transfers`
   with `on_hold: 1` → `HELD`. Otherwise `WAITING_ACCOUNT`.
2. **Order DELIVERED** (kitchen or courier, through
   `record_order_status_event`) → `PATCH /v1/transfers/:id` `on_hold: 0`
   → `RELEASED`. Pickup orders release on their DELIVERED (collected) step.
3. **Order cancelled / refunded before release** → refund with
   `reverse_all: 1` (or `POST /v1/transfers/:id/reversals`) → `REVERSED`.
4. **Webhooks** `transfer.processed`, `transfer.failed`,
   `settlement.processed` update the row. Same rule as the delivery webhook:
   a webhook is a nudge, the row is updated from a fetch of the transfer.
5. **Linked account becomes ACTIVE** → every `WAITING_ACCOUNT` row for that
   restaurant is transferred (and released at once if its order is already
   delivered).
6. Every Razorpay call runs in a Celery task **after commit**, keyed by
   `order_id`, so a retry never makes a second transfer: a row that already
   holds a `transfer_id` is never transferred again.
7. A daily beat task re-checks rows stuck in `HELD` for delivered orders and
   `FAILED` rows, and retries with a cap.

## Switches

- `ENABLE_RESTAURANT_PAYOUTS` — **default off.** Off: the ledger is still
  written (`WAITING_ACCOUNT` / computed shares) so the admin can see exactly
  what would be paid; no Razorpay call is made. On: transfers run.
- Per restaurant: the existing on/off switch on its own Razorpay keys. Off,
  with an ACTIVE linked account, means the platform collects (Bhagwati's
  path onto Route). See "Collecting on the platform's account".

## Screens

- **Super admin → Payouts** (Platform section): per restaurant — held,
  released, settled, waiting, problems — for the dashboard's period picker;
  a row per order with its status; Retry on `FAILED`/`BLOCKED` once fixed;
  CSV export.
- **Super admin → restaurant → Payout account**: the linked-account form,
  status, what Razorpay still needs, Refresh status.
- **Owner → Payouts**: their status, each order's share and where it is
  (held / on its way / in your bank), CSV statement. No commission rate is
  shown (commission stays admin-only).

## Errors

- Razorpay refuses a transfer → `FAILED`, Razorpay's sentence in
  `last_error`, shown to the admin with Retry. The order itself is never
  affected: a payout failure must not cost a sale.
- Network errors retry in Celery (bounded); a 4xx does not.
- The split not reconciling → `BLOCKED`, never a guessed amount.

## Testing

- `split.py`: pickup / delivery, GST inside and on top, discount, packaging,
  platform fee, null commission, negative share, reconciliation failure.
- Provider: request bodies for transfer, release, reversal, account steps
  (mocked HTTP), paise conversion, idempotency.
- Service (throwaway Postgres): payment → HELD; DELIVERED → RELEASED;
  cancel → REVERSED; no account → WAITING_ACCOUNT → transferred on
  activation; flag off writes the ledger and calls nothing; a retry never
  transfers twice.
- Admin: pure helpers for statuses and totals; build and lint at baseline.
- One end-to-end run against Razorpay **test mode** before the flag goes on.

## Outside the code (the platform owner)

- Ask Razorpay to enable **Route** on the platform account (KYC; days).
- Collect each restaurant's legal name, PAN, bank account, IFSC.
- Add Razorpay webhook events for transfers and accounts on the dashboard.
