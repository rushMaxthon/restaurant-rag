# Stripe Payment Integration Plan

Status: **implemented** (Card via Stripe PaymentSheet + COD). Phases 1–6 of §10 are
built; §10 phase 7 (live keys, real-card soak) and §12's open questions remain.
Last updated: 2026-08-13

Deltas from the plan as written, all deliberate:

* `GET /payments/config` also reports `supported_methods`, so CARD disappears from
  the app automatically when Stripe keys are absent.
* Order currency is stamped from `PAYMENT_CURRENCY` at creation, so the order and
  the charge can never disagree about units.
* `POST /orders` still *accepts* `payment_provider` / `payment_reference` from old
  clients but ignores both; they are marked deprecated in the schema.
* The unpaid-order reaper runs on Celery beat every 5 minutes (§7.4).
* `frontend-customer` (web) is untouched and remains COD-only in practice — see
  §12 question 4.

---

## 1. Scope

### In scope — exactly two payment methods

| Method | Provider | Flow |
| --- | --- | --- |
| **CARD** | Stripe | React Native PaymentSheet → backend PaymentIntent → webhook confirmation |
| **COD** | none | Order created directly with `payment_method = COD`; no gateway call |

Card work covers: backend PaymentIntent creation, Stripe webhook signature verification,
and success / failure / cancellation / retry handling on both ends.

### Explicitly out of scope

- Google Pay
- Razorpay
- Any other wallet or gateway (UPI apps, Apple Pay, PayPal, …)

These are **not** to be implemented or planned in detail now. Section 11 defines the seams
that keep them cheap to add later. `PaymentMethod.GOOGLE_PAY` and `PaymentMethod.RAZORPAY`
stay in the database enum (historical orders reference them) but are hidden from the
customer UI and rejected by the API until their provider is actually built.

---

## 2. Where the code stands today

Everything payment-related is currently a simulation. Facts, not assumptions:

| Area | Current state | File |
| --- | --- | --- |
| Card entry | Hand-rolled card form (number / expiry / CVV / name) with a Luhn check | `mobile/src/screens/payment/PaymentScreen.tsx` |
| "Payment processing" | `processOnlinePayment()` — a 1.2s `setTimeout`, then a fabricated reference `${provider}_${Date.now()}_${random}` | same file |
| Order creation | Single `POST /orders` call that *accepts* `payment_method`, `payment_provider`, `payment_reference` from the client | `backend/app/api/orders.py:37`, `mobile/src/services/api.ts` |
| Payment state | `orders.payment_status`, `payment_method`, `payment_provider` (default `"mock"`), `payment_reference` columns | `backend/app/models/order.py` |
| Enums | `PaymentStatus = PENDING \| PAID \| FAILED \| COD \| REFUNDED`; `PaymentMethod = GOOGLE_PAY \| RAZORPAY \| CARD \| COD`; `OrderStatus = PLACED \| ACCEPTED \| PREPARING \| OUT_FOR_DELIVERY \| DELIVERED` | `backend/app/models/enums.py` |
| Method availability | Per-branch `enabled_payment_methods` on `restaurant_locations`, enforced in `services/orders.py:324` | backend |
| Stripe config | `stripe_secret_key` / `stripe_publishable_key` exist in settings with mock defaults; **never read by any code** | `backend/app/config/settings.py:109` |
| Webhooks | None. No endpoint, no event log, no signature verification | — |

Three consequences drive the design below:

1. **The client currently asserts that payment succeeded.** Anyone can `POST /orders` with
   `payment_status`-implying fields and get a paid-looking order. The server must become the
   only authority on whether money moved.
2. **Raw card data touches our app.** The existing form is a PCI liability and must be
   deleted, not adapted — PaymentSheet never gives us the PAN.
3. **There is no order state for "awaiting payment."** `OrderStatus.PLACED` today means the
   kitchen can start cooking. A card order must not reach that state until Stripe confirms.

---

## 3. Target architecture

### 3.1 Chosen flow: order first, then payment

```
Customer taps "Pay"
      │
      ├─ COD ──────────────────────────────────────────────────────────────┐
      │                                                                     │
      ▼                                                                     ▼
POST /orders {payment_method: CARD}                          POST /orders {payment_method: COD}
  server prices the cart, creates order                        server prices the cart, creates order
  status = PAYMENT_PENDING                                     status = PLACED
  payment_status = PENDING                                     payment_status = COD
      │                                                                     │
      ▼                                                                  done
POST /orders/{id}/payment-intent
  server creates Stripe PaymentIntent for the
  server-computed total; returns client_secret
      │
      ▼
PaymentSheet presented in the app
      │
      ├── completed ──► webhook payment_intent.succeeded ──► payment_status = PAID,
      │                                                       status = PLACED
      ├── failed ─────► webhook payment_intent.payment_failed ► payment_status = FAILED
      │                 (order stays PAYMENT_PENDING, retryable)
      └── cancelled ──► app calls POST /orders/{id}/payment-cancel
                        (order stays PAYMENT_PENDING, retryable)
```

**Why order-first:** the PaymentIntent amount must come from the server's own pricing of the
cart (`services/orders.py` already computes subtotal, delivery fee, tax, discounts, and offer
eligibility). Creating the order first means one pricing pass, one source of truth, and a
durable row to attach the intent, the webhook, and any retry to. The cost is orders that
never get paid; section 7.4 covers reaping them.

**The client never reports payment success.** `payment_status` transitions to `PAID` only
from a verified webhook. The PaymentSheet result is treated as a UX hint for what to show
the customer, nothing more.

### 3.2 Provider abstraction

```
backend/app/services/payments/
├── __init__.py
├── base.py         # PaymentProvider protocol
├── stripe.py       # StripeProvider — the only implementation for now
└── registry.py     # PaymentMethod -> provider, gated by settings
```

```python
class PaymentProvider(Protocol):
    name: str  # persisted into orders.payment_provider, e.g. "stripe"

    def create_intent(self, *, order: Order, amount: Decimal, currency: str,
                      idempotency_key: str) -> PaymentIntentResult: ...
    def parse_webhook(self, *, payload: bytes, signature: str) -> WebhookEvent: ...
    def cancel_intent(self, *, reference: str) -> None: ...
    def refund(self, *, reference: str, amount: Decimal | None) -> RefundResult: ...
```

COD is deliberately **not** a provider — it is the absence of one. `registry.resolve(method)`
returns `None` for COD, and the order service takes the no-gateway branch.

---

## 4. Data model changes

### 4.1 Enum additions (Alembic migration, Postgres `ALTER TYPE ... ADD VALUE`)

| Enum | Add | Reason |
| --- | --- | --- |
| `OrderStatus` | `PAYMENT_PENDING` | Card order exists but is unpaid; must not reach the kitchen |
| `OrderStatus` | `CANCELLED` | Abandoned/expired unpaid orders, and future customer cancellation |
| `PaymentStatus` | `CANCELLED` | Customer dismissed PaymentSheet or intent was cancelled |

`PaymentStatus.PENDING/PAID/FAILED/COD/REFUNDED` already exist and keep their meanings.

Every consumer of these enums must be swept, because adding a status silently changes
behavior in list/filter code: restaurant order queues, `services/orders.py`, order status
transition validation in `PATCH /orders/{id}/status`, the admin dashboard, mobile
`OrderStepper`, and any notification triggers keyed on `PLACED`.

### 4.2 New table: `payment_transactions`

One order can have several payment attempts (retry after failure). The current single-row
`payment_reference` column cannot express that.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `order_id` | uuid FK → orders, indexed | |
| `provider` | varchar(50) | `"stripe"` |
| `provider_intent_id` | varchar(255), **unique** | `pi_...` |
| `status` | payment_status enum | attempt-level status |
| `amount` | numeric(10,2) | what we asked Stripe to charge |
| `currency` | varchar(3) | |
| `failure_code` / `failure_message` | varchar / text, nullable | surfaced on retry |
| `created_at` / `updated_at` | timestamptz | |

`orders.payment_reference` keeps pointing at the *successful* (or latest) intent id, so
existing reads keep working.

### 4.3 New table: `payment_webhook_events`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid PK | |
| `provider` | varchar(50) | |
| `provider_event_id` | varchar(255), **unique** | Stripe `evt_...` — the dedupe key |
| `event_type` | varchar(100) | |
| `payload` | jsonb | raw event, for forensics |
| `processed_at` | timestamptz, nullable | |

Stripe retries webhooks and can deliver out of order; the unique constraint on
`provider_event_id` makes handling idempotent by construction.

---

## 5. Backend work

### 5.1 Configuration

```
STRIPE_SECRET_KEY=sk_test_...          # already in settings, currently unused
STRIPE_PUBLISHABLE_KEY=pk_test_...     # served to the app, never hardcoded in the bundle
STRIPE_WEBHOOK_SECRET=whsec_...        # new
PAYMENT_CURRENCY=inr                   # new
PAYMENT_INTENT_TTL_MINUTES=30          # new — drives the reaper in 7.4
```

Startup validation: if `CARD` is enabled for any branch and the Stripe keys are still the
`sk_test_mock` defaults, log a loud warning (and fail hard in production).

### 5.2 Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/payments/config` | customer | Publishable key + merchant display name + enabled methods, so the key is not baked into the app binary |
| `POST` | `/orders/{order_id}/payment-intent` | customer (owner) | Create or reuse a PaymentIntent for the order; returns `client_secret`, `payment_intent_id`, `amount`, `currency`, `ephemeral_key`/`customer_id` if we adopt saved cards |
| `POST` | `/orders/{order_id}/payment-cancel` | customer (owner) | Customer dismissed the sheet; mark the attempt `CANCELLED` |
| `GET` | `/orders/{order_id}/payment-status` | customer (owner) | Short-poll fallback for the "webhook hasn't landed yet" window |
| `POST` | `/payments/stripe/webhook` | **none** (signature-verified) | Stripe event sink |

Rules for `/payment-intent`:

- Reject unless `order.payment_method == CARD` and `order.payment_status in (PENDING, FAILED, CANCELLED)`.
- Amount is **recomputed server-side** from the order rows — never read from the request.
- Idempotency key = `f"order:{order_id}:attempt:{n}"` so a double-tap cannot create two intents.
- Reuse the existing intent when one is still `requires_payment_method` / `requires_confirmation`.
- Stamp `metadata` with `order_id`, `customer_id`, `restaurant_id`, `app_client_id` — this is
  what makes a stray webhook traceable back to a row.

Rules for the webhook:

- Verify with `stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)`;
  a bad signature is a `400` and nothing else happens.
- Read the **raw request body** (FastAPI `await request.body()`), not the parsed model —
  re-serialized JSON breaks the signature.
- Insert into `payment_webhook_events` first; a unique-violation means "already handled" → `200`.
- Handle: `payment_intent.succeeded`, `payment_intent.payment_failed`,
  `payment_intent.canceled`, `charge.refunded`. Everything else: log and `200`.
- Always return `2xx` once persisted, even if downstream side effects fail — otherwise Stripe
  retries forever. Side effects (push notification, kitchen ticket) go through the existing
  notification service and are allowed to fail independently.

### 5.3 Order service changes (`backend/app/services/orders.py`)

- Stop trusting client-supplied `payment_provider` / `payment_reference`; derive both server-side.
- Branch on method:
  - `COD` → `status = PLACED`, `payment_status = COD`, `payment_provider = "cod"`.
  - `CARD` → `status = PAYMENT_PENDING`, `payment_status = PENDING`, `payment_provider = "stripe"`.
  - Anything else → `400 Payment method not supported`.
- Keep the existing `enabled_payment_methods` branch check; additionally intersect it with the
  set of methods the deployment actually supports (`{CARD, COD}`).
- Existing stock/price/offer validation runs **before** any intent is created, so we never take
  money for an order that would be rejected.

---

## 6. Status matrix

| Event | `order.status` | `order.payment_status` |
| --- | --- | --- |
| COD order placed | `PLACED` | `COD` |
| Card order created | `PAYMENT_PENDING` | `PENDING` |
| PaymentSheet completed, webhook received | `PLACED` | `PAID` |
| Card declined (`payment_failed`) | `PAYMENT_PENDING` | `FAILED` |
| Customer dismissed the sheet | `PAYMENT_PENDING` | `CANCELLED` |
| Retry succeeds | `PLACED` | `PAID` |
| Unpaid past TTL (reaper) | `CANCELLED` | `CANCELLED` |
| Refund issued | unchanged | `REFUNDED` |

Guard rails: the restaurant order queue and `PATCH /orders/{id}/status` must both refuse to
advance an order whose `payment_status` is not in `(PAID, COD)`.

---

## 7. Mobile work

### 7.1 Dependency

`@stripe/stripe-react-native` — requires a config plugin/pod install and `minSdkVersion 21+`;
wrap the app in `<StripeProvider publishableKey={...} merchantIdentifier={...}>` in
`mobile/App.tsx`, with the key fetched from `GET /payments/config` and cached, never hardcoded.

### 7.2 `PaymentScreen.tsx` rewrite

**Delete:** `CardFormState`, the card `TextInput`s, `formatCardNumberInput`,
`formatExpiryInput`, `passesLuhnCheck`, `createPaymentReference`, `processOnlinePayment`, and
the `GOOGLE_PAY` / `RAZORPAY` entries in `PAYMENT_COPY`. Card details are never to be typed
into our UI again.

**Keep:** the summary/address/fulfillment/offer sections, `enabled_payment_methods` gating
(now filtered to `{CARD, COD}`), and the existing `validateOrder` pre-check.

**New card path:**

1. `api.placeOrder(..., payment_method: 'CARD')` → order in `PAYMENT_PENDING`.
2. `api.createPaymentIntent(orderId)` → `client_secret`.
3. `initPaymentSheet({ paymentIntentClientSecret, merchantDisplayName: appConfig.display_name, allowsDelayedPaymentMethods: false })`.
4. `presentPaymentSheet()` → branch on the result (7.3).
5. On completion, poll `GET /orders/{id}/payment-status` (≈1s interval, ~10s ceiling) until
   `PAID`, then `clearCart()` and `navigation.replace('OrderSuccess', { orderId })`.
   If the poll times out, still go to OrderSuccess but show "Payment confirming…" — the order
   screen already re-fetches on focus, and the webhook will land.

**COD path:** unchanged from today minus the fake reference — one `placeOrder` call, straight
to `OrderSuccess`.

### 7.3 Result handling

| PaymentSheet result | UX | Cart | Order |
| --- | --- | --- | --- |
| Completed | "Payment successful" toast → OrderSuccess | cleared | awaiting webhook → `PAID` |
| `Canceled` | stay on PaymentScreen, "Payment cancelled — your order is saved" | **kept** | `POST /payment-cancel`; retry button visible |
| `Failed` | stay, show `error.localizedMessage` | **kept** | `FAILED`; retry button visible |
| Network error mid-flow | stay, "We couldn't confirm the payment" + Retry | **kept** | poll status before creating a second intent |

The cart is only cleared on a confirmed success — a customer who backs out must not lose
their basket. Retry re-uses `POST /orders/{id}/payment-intent` on the *same* order, so no
duplicate orders accumulate.

### 7.4 Unpaid order reaper

A periodic job (or lazy check on order read) cancels `PAYMENT_PENDING` orders older than
`PAYMENT_INTENT_TTL_MINUTES`, cancelling the Stripe intent as it goes. Without this, abandoned
checkouts pile up in the customer's order list.

### 7.5 Other surfaces

- `OrderStepper` / order detail: render `PAYMENT_PENDING` and `CANCELLED` states (today they
  assume `PLACED` is the start).
- Order list: an unpaid order should show "Payment pending — tap to complete" and deep-link
  back into the payment flow.
- `frontend-customer` (web) still uses the mock flow; it is **out of scope here** but will
  break against the new server rules once the client can no longer assert payment. Either
  freeze it or schedule Stripe.js Payment Element as a follow-up — decide before rollout.

---

## 8. Security

- Raw PAN never touches our servers, our logs, or the app — PaymentSheet tokenizes on-device.
- `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` live only in backend env; the app receives
  the publishable key at runtime.
- Webhook endpoint is unauthenticated by necessity — signature verification *is* the auth.
  Rate-limit it and keep the raw-body requirement in mind behind any proxy.
- Amounts are never accepted from the client. Ever. (Today they effectively are.)
- `console.log('[Payment] order payload:', …)` in `PaymentScreen.tsx` must go — it will
  otherwise log customer addresses and order contents in production.
- Every `payment_intent.succeeded` webhook must re-verify that the intent amount equals the
  order total before flipping to `PAID`.

---

## 9. Testing

**Backend**
- Unit: provider registry resolution; COD takes no gateway path; amount recomputation ignores
  client input; rejection of `GOOGLE_PAY`/`RAZORPAY`.
- Webhook: valid signature → status flip; tampered body → 400; duplicate `evt_` id → single
  effect; out-of-order `succeeded` after `payment_failed` → still ends `PAID`.
- Integration: full card order via Stripe test mode; `stripe listen --forward-to` for local
  webhook delivery.

**Test cards** (Stripe test mode): `4242…4242` success · `4000…0002` decline ·
`4000…9995` insufficient funds · `4000 0027 6000 3184` 3DS required.

**Mobile**
- COD order unchanged end to end.
- Card: success, decline, cancel-then-retry, kill-app-mid-sheet (order recoverable).
- Cart survives cancellation; cart clears only on success.

---

## 10. Phasing

| Phase | Deliverable | Done when |
| --- | --- | --- |
| 1 | Migrations: enum values, `payment_transactions`, `payment_webhook_events` | `alembic upgrade head` clean on a copy of prod |
| 2 | Provider abstraction + Stripe intent creation + `/payments/config` | Intent visible in Stripe dashboard with correct metadata |
| 3 | Webhook endpoint + verification + idempotency + status transitions | `stripe trigger payment_intent.succeeded` flips a real order |
| 4 | Order service split (COD vs CARD) + status guards on the kitchen queue | Unpaid order cannot be advanced by a restaurant |
| 5 | Mobile PaymentSheet, mock form deleted, retry/cancel handling | All 7.3 rows behave as tabled |
| 6 | Reaper, order-list "payment pending" affordance, admin visibility | Abandoned order auto-cancels within TTL |
| 7 | Test-mode soak, then live keys behind a per-branch flag | Real card charged in staging |

Phases 1–4 are backend-only and ship without touching the app; the app keeps working on COD
throughout (card is simply unavailable until phase 5).

---

## 11. Keeping it extensible

The seams that make Google Pay / Razorpay / wallets additive rather than invasive:

- **`PaymentProvider` protocol** — a new gateway is a new module plus a registry entry; the
  order service, webhook table, and transaction table are provider-agnostic already.
- **`PaymentMethod` enum keeps its unused values** — no migration needed to re-enable them.
- **`payment_transactions.provider` + `provider_intent_id`** — generic naming, not `stripe_*`.
- **`payment_webhook_events.provider`** — one table serves every gateway's event log.
- **Per-branch `enabled_payment_methods`** — the existing admin control already gates
  availability; a new method becomes visible by enabling it, not by shipping UI logic.
- **`GET /payments/config`** returns the supported-method list, so the app renders whatever
  the backend says it supports without a release.

Google Pay in particular later rides on Stripe's own PaymentSheet (`googlePay: {...}` in
`initPaymentSheet`) rather than a separate integration — so this plan positions it as a
config change, not a project. That is noted only to justify the shape; **it is not being
built now.**

---

## 12. Open questions

1. **Currency.** Prices render as `₹`, so `PAYMENT_CURRENCY=inr`. An INR-charging Stripe
   account must be India-registered, and Indian regulation restricts what such an account can
   charge internationally — confirm the Stripe account's country before phase 2.
2. **Saved cards.** PaymentSheet supports returning customers via a Stripe Customer +
   ephemeral key. Worth it now, or defer? (Deferring means no `stripe_customer_id` on `users` yet.)
3. **Refunds.** `PaymentStatus.REFUNDED` exists but nothing issues refunds. Admin-triggered
   refund UI — this project or a follow-up?
4. **Web client.** Freeze `frontend-customer` at COD-only, or fund Stripe.js in parallel?
5. **Restaurant payout / Connect.** Single merchant account collecting for all restaurants, or
   Stripe Connect per restaurant? This materially changes phase 2 and should be settled first.
