# Paying restaurants: Razorpay Route

Spec: `docs/superpowers/specs/2026-10-05-restaurant-payouts-design.md`.
Code: `app/services/payouts/`, `app/api/payouts.py`, `app/tasks/payouts.py`,
migration `0083_restaurant_payouts`.

The platform's own Razorpay account collects a restaurant's online payment,
and Razorpay Route passes the restaurant's share on to its bank. Every step
is written to a ledger, one row per order, so the admin and the owner can see
where each rupee is.

## The split (`services/payouts/split.py`, and only there)

```
restaurant_share = subtotal - commission - discount + packaging + food GST
platform_keeps   = commission + delivery fee + delivery GST + platform fee
```

- **Commission comes back out of the subtotal.** The menu price is the
  restaurant's price with the platform's percentage folded in, so the
  subtotal already contains it.
- **Discounts come out of the restaurant's share.** An owner runs offers for
  their own kitchen.
- **Delivery and its GST are the platform's,** because the platform pays the
  rider.
- **Razorpay's fee is the platform's cost.** It is in neither figure, so a
  restaurant's share never shrinks with the gateway's fee.

The two must add up to `total_amount` to the paisa. If they do not, the row
is `BLOCKED` with the difference, and nothing is transferred. This is what
orders from before food GST and delivery GST were stored apart will show.

## Statuses and what moves them

| Status | Means | Moved by |
|---|---|---|
| `WAITING_ACCOUNT` | Paid on the platform account, not transferred yet | Payment confirmed (`_mark_paid`) |
| `HELD` | Transferred, on hold until the food is handed over | The transfer task |
| `RELEASED` | Hold lifted; Razorpay settles it on its schedule | DELIVERED (`record_order_status_event`) |
| `SETTLED` | In the restaurant's bank | A transfer webhook, then a fetch, or the hourly sweep |
| `REVERSED` | Taken back | CANCELLED or a refund |
| `FAILED` | Razorpay refused; Retry once the cause is fixed | A 4xx from Razorpay |
| `BLOCKED` | The split did not reconcile | `split_order` |
| `NOT_APPLICABLE` | COD, Stripe, or the restaurant's own keys: money never passed through the platform | Recorded so every order's split is visible |

Every Razorpay call runs in Celery after the order's transaction commits.
Each call holds a row lock (`with_for_update`), and a row that already has a
`transfer_id` is never transferred again. Razorpay would accept a second
transfer from the same payment, so that check is what stands between a retry
and paying a restaurant twice.

## When the platform collects

The platform's Razorpay account takes a restaurant's payment only when all of
these hold:

- `ENABLE_RESTAURANT_PAYOUTS` is on.
- The platform keys are real, not the `rzp_test_mock` default.
- The restaurant's linked account is `ACTIVE`.
- The restaurant has no enabled Razorpay keys of its own.

Anything less, and money would sit with the platform with no way to pass it
on. A restaurant with its own keys keeps being paid directly. To move one
onto Route, switch its own keys off once its linked account is ACTIVE.

Each payment remembers which account took it
(`payment_transactions.on_platform_account`). Confirming, reconciling and
cancelling an attempt always use that account, even after the flag is
switched off.

## The switch

`ENABLE_RESTAURANT_PAYOUTS` defaults to off. While it is off, the ledger is
still written for every paid order, so the Payouts page shows exactly what
would be paid, and Razorpay is never called.

## Setup

Environment variables, on Render and locally:

- `ENABLE_RESTAURANT_PAYOUTS`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `RAZORPAY_WEBHOOK_SECRET`

Webhook URL on the platform's Razorpay dashboard:
`https://<api host>/api/payments/razorpay/webhook`. Tick these events:

- Payments: `payment.captured`, `payment.failed`, `order.paid`
- Refunds: `refund.created`, `refund.processed`
- Transfers: `transfer.processed`, `transfer.failed`
- Settlements: `settlement.processed`
- Linked accounts: `product.route.activated`,
  `product.route.needs_clarification`, `product.route.under_review`,
  `account.suspended`

A webhook is a nudge. A transfer event queues a fetch of the transfer, and
the row moves on what Razorpay answers.
Events are de-duplicated on Razorpay's `X-Razorpay-Event-Id` header (the
body carries no id), falling back to the entity the event names.

Only a refund of the whole order takes the restaurant's share back. A partial
refund is written on the payout row for the admin to decide, because it is a
choice about who bears it.

Before every transfer, the platform asks Razorpay for any transfer already
made from that payment for that order, and adopts it. A create that timed out
may still have been accepted, and sending it again would pay twice.

## Test-mode checklist (before the flag goes on in production)

1. Ask Razorpay to enable **Route** on the account, in test mode first.
2. Locally, set test keys and `ENABLE_RESTAURANT_PAYOUTS=true`. The local
   database must be at `0083`.
3. Payouts → pick a restaurant → fill in the bank account form with
   Razorpay's test PAN and bank details → Save → **Send to Razorpay**.
4. Activate the linked account from the Razorpay test dashboard, then press
   **Refresh status**. It should read Active.
5. Place a Razorpay test order at that restaurant. Its row should read
   **Held**, and the Razorpay dashboard should show a transfer on hold.
6. Mark the order Delivered. The row should read **Released**.
7. Place another order and let it be cancelled. The row should read
   **Reversed**.
8. If Razorpay refuses a v2 onboarding field, fix the name in
   `route_client.py`. Those bodies follow Razorpay's published docs and are
   proven only by this run.
