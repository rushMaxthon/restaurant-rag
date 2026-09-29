# Getting the food to the customer

How an order becomes a courier job, what happens to it, and the three places
this can cost real money if it is changed carelessly.

One courier is integrated today — **Pidge** — behind a contract that assumes
there will be others.

---

## The shape

```
app/services/delivery/
  base.py            DeliveryState, DeliveryRequest/Result, the protocol
  pidge_provider.py  login + token cache, create, fetch, parse_webhook
  registry.py        which courier answers
  service.py         order -> request, result -> row, and the order's status
app/tasks/delivery.py      the dispatch task
app/api/delivery.py        the status webhook
app/models/order_delivery.py   one row per order
frontend-admin/src/components/DeliveryPanel.tsx
```

Same arrangement as `services/payments`, deliberately: a second courier should
be a module and a registry entry, not a change to the order flow.

## The journey

```
kitchen accepts the order
  -> update_order_status queues dispatch_order_task   (after the commit)
  -> the task calls Pidge and writes an order_deliveries row
  -> Pidge pushes status changes to /api/delivery/webhook
  -> the webhook ASKS Pidge what really happened, and records that
  -> IN_TRANSIT and DELIVERED move the order; nothing else does
```

Verified end to end against Pidge's sandbox. A forged webhook claiming
`DELIVERED` left the order on `ACCEPTED`, because the courier was asked and
said "pending".

## Credentials are platform-level, not per-restaurant

The opposite of payments, and on purpose. A restaurant's payment account is
its own money and must be its own keys. A courier account is the **platform's**
commercial relationship: Pidge distinguishes tenants by `brand.code` and
`location_code` inside one account, not by separate logins. Per-restaurant
courier credentials would mean one Pidge contract per restaurant, which is not
how the product is sold.

⚠️ **`brand` only works on an aggregator account.** Pidge refuses it on a
vendor account — "Brand is allowed only for aggregator(6)" — and the sandbox
account is type 4. Until Pidge provisions an aggregator account, the block is
omitted entirely and tenants are indistinguishable to them. **This blocks real
multi-tenant use.**

## Why the delivery has its own state

`orders.status` is the RESTAURANT's lifecycle and is strictly linear:
`PLACED -> ACCEPTED -> PREPARING -> OUT_FOR_DELIVERY -> DELIVERED`, plus
`CANCELLED`.

A courier has an outcome that fits nowhere on that line: a rider collects the
food, cannot hand it over, and brings it back. That is not `CANCELLED` —
nothing was called off, the food was cooked and is now spoiled — and it is
certainly not `DELIVERED`. Folding it into `CANCELLED` erases the difference
between an order nobody started and one that was made, dispatched and wasted,
which is exactly the case somebody has to pay for.

So sixteen Pidge statuses collapse into seven of ours:

| Pidge | Ours | Moves the order to |
|---|---|---|
| CREATED, PENDING | `PENDING` | — |
| OUT_FOR_PICKUP, REACHED_PICKUP | `ASSIGNED` | — |
| PICKED_UP | `PICKED_UP` | — |
| IN_TRANSIT, OUT_FOR_DELIVERY, REACHED_DELIVERY | `IN_TRANSIT` | `OUT_FOR_DELIVERY` |
| DELIVERED | `DELIVERED` | `DELIVERED` |
| CANCELLED | `CANCELLED` | — |
| UNDELIVERED, RTO_*, DISPOSED, LOST, DAMAGED | `FAILED` | **nothing** |

`FAILED` moves nothing. The order stays where it was, the failure is visible in
the admin, and a person decides. Who pays for a delivery that came back is a
commercial question, not one a status machine should answer by itself.

An unknown status becomes `PENDING` rather than raising: a courier adding to
its own vocabulary must not take an order down, and `PENDING` keeps everything
watching.

## The webhook does not believe its payload

**Pidge signs nothing.** No signature header, no shared secret, nothing in
their documentation. An endpoint that moves an order to `DELIVERED` on the
strength of an unauthenticated POST is one where anyone who learns the URL can
close every ticket in a kitchen and strand the food.

So a push is a **nudge, never news**:

1. Read one field from the body — which delivery it concerns.
2. Fetch that delivery from Pidge over our own authenticated connection.
3. Record what the *fetch* said.

A forged POST costs one API call and changes nothing.

`DELIVERY_WEBHOOK_SECRET` is defence in depth and deliberately not the
guarantee — it travels in a header, and headers end up in logs and proxies.
When Pidge adds signing, it becomes a real check and the fetch becomes an
optimisation.

Everything answers **200**. A courier reading anything else retries, and a
retry storm over a payload we deliberately ignored helps nobody. An unknown
delivery id is accepted and ignored rather than refused, so the endpoint cannot
be used to probe which ids exist.

## Three things that cost money if you change them

**A second rider.** `order_deliveries.order_id` is `UNIQUE`, and `dispatch`
claims the row with a flush **before** calling the courier. Two workers racing
lose on the constraint rather than booking two riders. Do not remove either
half — the check is the fast path, the constraint is the guarantee.

**A rider asking for money already paid.** `cod_amount` is the order total only
when the payment method is COD, and zero otherwise. Getting this backwards has
a customer asked to pay twice at their own door.

**An order dragged backwards.** Status pushes arrive late and out of order.
`advance_order` only ever moves forward along the flow, so a stale `IN_TRANSIT`
landing after `DELIVERED` is ignored. Without it, a customer is told their
delivered dinner is on its way.

## Where the documentation is wrong

Written against the sandbox, not the Postman page. Each of these is a 400 in
production and an order nobody collects:

| Documented | Actually |
|---|---|
| address `line1` | **`address_line_1`** |
| notes `{key, value}` | **`{name, value}`** |
| create returns `data.id` | **keyed by YOUR `source_order_id`**: `{"data": {"ORD-1": "1790…"}}` |
| `brand` accepted | refused on a vendor account |

Undocumented but useful: the order carries **`pickup_drop_distance`** in metres.
It is the only distance figure this app has, and what a distance-based delivery
fee would be priced from — which partly covers Pidge having no quote endpoint.
Package dimensions feed their volumetric weight, so they affect the price;
placeholders there are a wrong invoice later.

## Switching it on

Off by default. Nothing calls Pidge until `ENABLE_DELIVERY_DISPATCH` is true
**and** credentials exist.

```
ENABLE_DELIVERY_DISPATCH=true
PIDGE_BASE_URL=https://store.dev.pidge.in
PIDGE_USERNAME=…
PIDGE_PASSWORD=…
PIDGE_BRAND_CODE=…            # aggregator accounts only; leave empty otherwise
DELIVERY_WEBHOOK_SECRET=…     # optional
```

Point Pidge's webhook at `POST /api/delivery/webhook`.

## Still open

- **An aggregator account from Pidge.** Blocks per-tenant brand mapping.
- **No cancel endpoint** is documented. If an order is cancelled after a rider
  is dispatched, there is no way to call it off from code — ask Pidge whether
  one exists.
- **No serviceability or quote endpoint.** You cannot tell a customer the
  delivery fee, or whether an address is deliverable, before they pay.
- **Migration `0069` is forked.** This branch's `0069_order_deliveries` and
  `marketing`'s `0069_campaign_recipients` both descend from `0068`, and the
  shared database reads `0071`. The migration is written to tolerate the table
  already existing, but the chains still need an `alembic merge`.
