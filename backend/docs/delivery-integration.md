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
  -> PICKED_UP / IN_TRANSIT and DELIVERED move the order; nothing else does
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

## Status is PULLED, and pushed as a bonus

**Pidge has no API to register a webhook.** Probed: `/vendor/webhook`,
`/vendor/settings` and `/vendor/profile` all refuse. The push URL is configured
on their side, which means a deployment that has not arranged it yet would show
every rider as PENDING forever.

So `app.tasks.delivery.refresh_deliveries_task` runs every minute and asks the
courier about every delivery still in flight. The webhook is an accelerator on
top of that, not the mechanism. Even once Pidge is pushing, a push that is
dropped, retried into a closed port, or sent while this service restarts is
simply lost with nothing to correct it — the sweep corrects it within a minute.

Both paths go through the same `record`, so a delivery's state changes one way
however the news arrived.

⚠️ **Only unfinished deliveries are asked about**, filtered in the query rather
than after it. A terminal delivery cannot change, and re-asking would mean one
HTTP call per completed order, forever.

The admin panel polls its own API every ten seconds while a delivery is in
flight and **stops on a terminal state**, for the same reason.

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

## Calling a rider off

`POST /v1.0/store/channel/vendor/{id}/cancel` — the fourth of Pidge's core
calls, after login, create and status. This document used to say no cancel
endpoint was documented. It is; it had not been looked for, because nothing
needed it.

Nothing needed it because every cancellation on this platform is of an UNPAID
order (`OrderCancellationReason`), and dispatch happens when the kitchen
accepts — so no order that can be cancelled today has ever had a rider. The
call is wired in anyway, at the one place an order is cancelled:

```
mark_order_cancelled
  -> if the order has a delivery row carrying Pidge's id,
     queue cancel_order_delivery_task               (after the commit)
  -> the task RE-READS the order and stops unless it is CANCELLED
  -> service.cancel asks Pidge, and marks the row CANCELLED only if they agree
```

Three things about it that are easy to get wrong:

- **The path has no `/order/` segment.** Every other call is
  `/vendor/order/...`. Written by analogy it 404s, which reads like an unknown
  order rather than an unknown route.
- **Pidge refuses once the food is collected** — only `PENDING` and
  `FULFILLED` may be cancelled; after that it is 400
  `order.action.cancel.not-allowed`. That refusal is stored in `last_error` and
  the row keeps its real state. A row that said CANCELLED while a rider was
  riding to a door would be worse than no cancel at all.
- **It is not behind `enable_delivery_dispatch` or the live-host interlock.**
  Those stop a rider being booked. Turned off after one was sent, they must
  not also stop the rider being recalled.

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
Package dimensions feed their volumetric weight, so they affect the price;
placeholders there are a wrong invoice later.

**They do price ahead of time, and the Postman page does not say so.** Three
endpoints exist and all three answer:

| Endpoint | Answers | Coordinate keys |
|---|---|---|
| `POST .../vendor/serviceability` | will anyone drive it | `lat` / `lng` |
| `POST .../vendor/estimate` | what it costs | `latitude` / `longitude` |
| `POST .../vendor/quote` | a multi-drop batch | `pickup.coordinates`, `drop` as an array with `ref` |

The two we use **disagree about what a coordinate is called**, which is a 400
if you assume they match. `estimate` answers with `minCost`, `maxCost`,
`pickupToDropDistance`, `pickupToDropTime` and `timeToAssign`.

## What delivery costs, before the order exists

A flat `restaurant_location.delivery_fee` charged the customer next door and
the customer across the city the same amount. A courier prices by distance, so
the restaurant carried that difference without ever seeing it.

```
checkout types an address
  -> POST /api/orders/delivery-quote
  -> geocoding turns both ends into points     (a STAND-IN today)
  -> Pidge says serviceable, then prices it
  -> the checkout shows the courier's number
  -> placing the order recomputes it server-side from the same rule
```

Measured against their sandbox, from Bodakdev in Ahmedabad:

| Drop | Distance | Quoted |
|---|---|---|
| next street | 441 m | ₹30 – ₹50 |
| Navrangpura | 6.7 km | ₹67.04 – ₹87.04 |
| Maninagar | 13.1 km | ₹131.14 – ₹151.14 |

**A band, not a price**, because no rider has been assigned yet.
`DELIVERY_QUOTE_BASIS` chooses which end is printed and defaults to `max` —
the only end that cannot leave the platform paying the difference on a busy
evening.

**The branch's flat fee is the fallback for everything.** Flag off, no
credentials, courier slow, courier down, address unserviceable, courier
quoting a currency this order is not in — each one lands on the fee every
order has charged until now. That is what makes switching this on safe: with
the flag off, nothing anybody pays changes.

⚠️ **A courier quoting the wrong currency is discarded, not converted.** Found
by running it: Pidge quoted ₹87.04 for a branch that bills in CAD, and adding
those produces a figure that is not money in any currency. Converting would
need an exchange rate nobody chose, applied to an amount the restaurant never
agreed to charge.

**Nothing here invents a number.** There is no default courier fee and no
distance formula of our own. The only figures that reach a customer are the
branch's own fee or the courier's own quote — the stand-in is in the
COORDINATES, never in the price.

### The courier's figure already contains GST

Pidge quotes what it will invoice, and that is inclusive of 18%. The bill has
its own "GST on delivery fee" line at the branch's `delivery_tax_percent`, so
charging the quote as the fee taxed one delivery twice — a 59.00 trip reached
the customer as 69.62.

`quoting.before_delivery_tax` takes the tax back out before the fee is stored:
59.00 becomes a fee of 50.00, the tax line adds 9.00, and the customer pays
what the courier charges. Both the quote endpoint and `create_order` go
through it, so the checkout and the order cannot disagree.

It uses the branch's own rate, and takes nothing out when that rate is zero —
which it is by default. So for the customer to see the split, the branch must
have `delivery_tax_percent` set to 18. It is never applied to the branch's
flat fee, which is a number the owner typed.

Checked live on 2026-10-05 against Bhagwati Bakery: courier 50.00, fee 42.37,
GST 7.63.

## What delivery costs, after a rider is assigned

The estimate is not the bill. The account auto-allocates, so Pidge picks the
rider network the moment the order is created, and that network's price is
only known once a rider is on the way. On 2026-10-06 the same 3.7 km trip,
estimated at about Rs 57, went to porter at Rs 76.69 and to wefast at
Rs 285.61, twice. Our own `pick_network` (cheapest first) never ran: it only
acts on an order Pidge left unallocated.

So the guard is after the fact, and it flags rather than cancels - the food
still goes out, and a cancel would cost a delay and maybe a fee, and an
auto-allocating account could hand the retry to the same network.
`courier_overpriced` holds `courier_charge` against what the customer paid
(`delivery_fee` plus `delivery_tax_amount`) and flags it past
`COURIER_OVERPRICE_RATIO` (1.5). Free delivery is never flagged. The flag is
on the order's delivery card and in Platform Watch, and a warning is logged
when the price first arrives. Like the charge itself, only the platform
admin sees it: beside the fee it is the platform's margin.

## The tracking link is a code, not a URL

Confirmed by Pidge directly. Their webhook carries a short code:

```
track_code: "iaseov"
```

and the page is that code dropped into an address they publish:

```
https://tracking.pidge.in/?t={code}
```

`PIDGE_TRACKING_URL` holds the template, because the domain is theirs and a move
should be an environment variable rather than a release.

⚠️ **This reader used to look for a `tracking_url` field**, which Pidge has never
sent, so the link was always empty — and an empty link looks exactly like a
rider who has not been assigned yet. Nobody could have told the difference from
the screen. A literal URL still wins if one ever appears, because a link they
sent beats one we assembled.

The same link is shown to both sides: "Follow the rider" in the admin's Courier
card, "Track on the map" on the customer's order page.

## Where an address becomes a point

A courier prices a trip between two COORDINATES, and until this existed the app
had none: branch `latitude`/`longitude` columns nobody filled in, and a
customer's address as free text with nowhere to put one. Every quote priced the
same stand-in trip.

```
app/services/geocoding/
  base.py        AddressQuery, GeocodedPoint, GeocodeConfidence, the protocol
  google.py      geocoding + Places autocomplete. Accurate. Needs a key.
  nominatim.py   OpenStreetMap. No key, no account, works immediately.
  registry.py    Google when a key exists, OSM otherwise
  service.py     locate(): the three cache layers
app/api/addresses.py                     /suggest and /resolve
app/services/delivery/geocoding.py       the seam: branch + address -> points
scripts/locate_branches.py               locate every branch, report failures
frontend-customer/src/components/AddressAutocomplete.tsx
```

### The dropdown is the accurate path

Geocoding what somebody typed is a guess. Having them PICK a place and taking
the coordinates from that place's own record is not. So the checkout's first
address box is an autocomplete, and a picked place sends its latitude and
longitude with the quote — the courier then prices the building the customer
pointed at.

It proxies through `POST /api/addresses/suggest` and `/resolve` rather than
loading Google's JavaScript with a key in the bundle. Three reasons, in order of
weight:

1. **The key never reaches a browser.** A referrer-restricted browser key is
   normal practice and not wrong, but it is a credential with a billing quota in
   public.
2. **The session token is managed in one place.** Providers bill autocomplete
   per SESSION when the keystrokes and the final details call share a token, and
   **per request** when they do not. A client that forgets it turns one charge
   into one per character typed.
3. **Resolved coordinates get stored** on the customer's saved address, so their
   next order is priced with no provider call at all.

With no key configured, `/suggest` answers `available: false`, the dropdown
never appears, the form behaves exactly as before, and the backend geocoder
still prices the order. A missing dropdown costs accuracy, never correctness.

### A geocoder never says no

This is the failure the whole package is shaped around. Ask for "12 Fake Street,
Nowhere" and a geocoder returns the centroid of the nearest city with a 200 and
no complaint. A delivery priced from a country centroid is a real courier price
for a trip nobody is taking, and it is indistinguishable from a correct answer.

So `GeocodeConfidence` grades every answer and only `ROOFTOP` and `STREET` may
price a delivery. `exact_location` on the quote response means "precise enough to
charge for", not "something answered". Measured:

| Asked | Got | Priced from |
|---|---|---|
| Ashram Road, Ahmedabad | `STREET` | yes |
| Yonge Street, Toronto | `STREET` | yes |
| 380015, Ahmedabad | `POSTCODE` | no — an Indian PIN spans kilometres |
| Kankaria Lake, Ahmedabad | `LOCALITY` | no — a landmark, not a door |
| 12 Nowhere Street, Atlantis | not found | no |

### ⚠️ OpenStreetMap is not enough for India

Measured against real Ahmedabad addresses, not assumed. Nominatim finds
numbered streets and finds **none** of these:

```
Shivalik Plaza, Ahmedabad                  0 results
Iscon Cross Road, S G Highway, Ahmedabad   0 results
Singanpor, Surat                           0 results
```

All 18 seeded branches came back not found. Indian addresses are written from
societies, malls and crossroads, which is the half of the map OSM is thinnest
on. **Set `GOOGLE_MAPS_API_KEY` for the India deployment.** The fallback exists
so the feature works at all without an account, not because it is sufficient.

Also measured: Nominatim's **structured** search (`street=`, `city=`) returns
nothing for these and freeform finds them, because it treats `street` as a field
that must match an OSM street and will not fall back. Google is the opposite way
round. That is why each provider builds its own request from `AddressQuery`
instead of a shared builder deciding for both.

### ⚠️ The branch's own coordinate is half the price

Easy to overlook, because the customer's address is the one being typed. Pidge's
`estimate` takes **two coordinate pairs and no addresses** — there is no form of
the call that accepts a street — so the pickup point has to come from us, and
the pickup point is the branch.

A branch with no coordinates used to fall through to the stand-in, and the
result was not subtly wrong. Caught in a browser: the stand-in is in Ahmedabad,
the customer was in Surat, and the courier honestly priced **258 km — ₹2,601.48
delivery on a ₹50 loaf of bread**, printed as the fee. Pidge was not wrong. It
was asked about a journey nobody was making.

**So a stand-in at either end is not quoted at all.** The branch's flat fee
stands and `source` says `branch`. The distinction is invented versus vague: a
geocoder that only reached a suburb still answered about the real address, so
the distance is roughly right and the price is worth showing. A stand-in is a
constant with no relationship to the order.

#### Three ways a branch gets located

| | How | Stored confidence |
|---|---|---|
| 1 | **Paste from a map.** Latitude and longitude fields on the branch form and the create form. Right-clicking a door in Google Maps copies the pair. | **empty**, meaning a person put it there |
| 2 | **"Find from the address above"** on the branch page, or `scripts/locate_branches.py --write` in bulk. | whatever the lookup said |
| 3 | Automatically on the first quote, written back onto the row. | only on a precise match |

`restaurant_locations.geocode_confidence` records which. **Empty means SET BY
HAND and is the most trusted value, not the least** — somebody pointed at their
own front door, which beats any geocoder. Saving the pair from the admin form
clears it for exactly that reason.

Option 2 answers and does **not** save. A geocoder never refuses, so reading
`matched` back is the only thing that catches a lookup that landed confidently
in the wrong suburb — and it does happen: "Dragon Wok CG Road" resolves to
`New C.G. Road, Chandkheda`, which is a different part of Ahmedabad entirely,
and comes back marked STREET.

#### Asking progressively less

A branch address here names a building no map has heard of, with a real
neighbourhood on the end: "Shop 12, Maple Trade Center, **Bopal**". So
`services/geocoding/branches.py` asks four questions and stops at the first
answer — the full address, the last fragment of line 1, the branch's own name
(they are named after where they are), then the postcode.

That turned **0 of 25** branches located into **25 of 25**:

| Confidence | Branches | Used for pricing |
|---|---|---|
| ROOFTOP / STREET | 9 | yes, and trusted |
| LOCALITY | 14 | yes, flagged imprecise |
| REGION | 2 | **no** |

#### Three tiers, not two

`Coordinates.usable` is the rule, and the middle tier is the point of it:

- **Exact** — a door, or a hand-typed pair. Priced and trusted.
- **Usable but not exact** — a neighbourhood. Priced, flagged. Right to within a
  kilometre or two, which is a real answer for a delivery fee. Refusing it would
  throw away the only point 14 of 25 branches have.
- **Neither** — a stand-in, or a district centroid. Not priced at all. A REGION
  match is a real coordinate for the wrong scale of thing: "somewhere in this
  taluka" can be ten kilometres out, and a fee built on it is wrong by more than
  the fee.

Measured from the Surat branch as located today (LOCALITY, via its postcode):

| Drop | Distance | Fee |
|---|---|---|
| Ring Road | 3.3 km | ₹52.89 |
| Athwalines | 5.4 km | ₹74.44 |
| Adajan | — | flat fee: nothing usable resolved |

### Nothing is looked up twice

Three layers, cheapest first:

1. **The row.** A branch's stored coordinates, or a saved address the customer
   picked. Free, and the reason a returning customer costs zero provider calls.
2. **`geocode_cache`**, keyed by a hash of the normalised address text.
3. **Redis**, in front of the table.

A NULL latitude in `geocode_cache` is a remembered **miss**. An address that
will not resolve today will not resolve on the next page load, and re-asking
every time is how a quota disappears quietly.

⚠️ **Only a real "no match" is cached.** A timeout or a rejected key says nothing
about the address. This bit during development: a misconfigured provider cached
misses for every address tried during it, and the addresses kept failing after
the bug was fixed. `test_a_transport_failure_is_not_remembered` is the guard.

### When a branch cannot be located

`scripts/locate_branches.py` geocodes every branch and prints three lists:
located, too vague to trust, and not found. `--write` stores only the precise
ones. Nothing is stored without it, because coordinates decide what customers
are charged.

For the rest, the branch form in the admin now has latitude and longitude
fields. Right-clicking a spot in Google Maps puts the pair on the clipboard.
This is the escape hatch that always works, and for a society or a mall in India
it is faster than arguing with a geocoder.

## What the courier tells us, and where it lands

Captured from the sandbox on 2026-10-05, eight stages from booked to
delivered, stripped of personal fields and kept as
`tests/fixtures/pidge_sandbox_states.json` — `test_delivery_tracking` reads
every expectation below from those real bodies, not from the documentation.

| Pidge field | Stored as | Used for |
|---|---|---|
| `fulfillment.status` | `state` | the delivery's own state machine |
| `fulfillment.pickup.eta` / `drop.eta` | `pickup_eta` / `drop_eta` | "Arriving by 8:16 pm" for the customer, the ETA on the live board |
| `fulfillment.pickup.timestamp` | `picked_up_at` | the real collection time |
| `fulfillment.drop.timestamp` | `delivered_at` | only when DELIVERED — an undelivered trip has a drop timestamp too |
| `fulfillment.delivery_charge` | `courier_charge` | what Pidge bills us. **ADMIN only** — `for_viewer` removes it for an owner |
| `fulfillment.logs[]` | `timeline` | every step, oldest first: the admin's trip history and the customer's "Your rider is at the restaurant" |
| the last log carrying a location | `rider_latitude/longitude/_at` | "last seen" map link in the admin |
| the remark on an UNDELIVERED/RTO log | `failure_reason` | why a trip failed, said to the owner |

The rider's live position also comes from `GET /fulfillment/tracking`, which
Pidge rate-limits to **once per 30 seconds per order**. The minute sweep asks
it only for ASSIGNED, PICKED_UP and IN_TRANSIT rows, so it stays inside that.

### A courier step moves the order the same way a kitchen does

The courier used to set `order.status` and nothing else. No status event was
written, so the order vanished from "Done today" and its history; no push went
to the customer; no realtime hint reached the board. A rider's DELIVERED was
quieter than a cook's tap.

Now `record` calls `record_order_status_event` (actor SYSTEM, note
`courier: <status>`, `metadata.source = "courier"`, `occurred_at` = Pidge's
own drop timestamp for DELIVERED) and queues the customer notification
**after commit**, through the same task the kitchen path uses. `PICKED_UP`
now moves the order to OUT_FOR_DELIVERY — before, the order sat at PREPARING
while the food was on a bike.

### A failed trip can be re-booked

`POST /orders/{id}/delivery/rebook` (ADMIN, OWNER), offered only when the row
is FAILED or CANCELLED and the order is still ACCEPTED, PREPARING or
OUT_FOR_DELIVERY. It reuses the row, bumps `attempt`, and books under the
reference `{order_id}-{attempt}` — Pidge refuses a reference it has seen, and
the original would be a duplicate. The `should_dispatch` guards still apply, so
a re-book cannot get round the live-host interlock.

`POST /orders/{id}/delivery/cancel` is the button the "Still open" list used to
ask for: the owner can call a rider off while the order stands. Pidge's own
refusal after collection comes back as a 409 with their sentence.

### Simulating a trip

`POST /orders/{id}/delivery/simulate` (ADMIN) asks Pidge's sandbox to move the
order with `?dummy_status=fulfilled|picked up` and records the answer. It is
refused unless `PIDGE_BASE_URL` is the sandbox host, so it cannot exist against
a real rider. The admin shows the stage buttons only when the API says
`can_simulate`.

### What Pidge offers that we still do not use

- **Update order details** after booking (a corrected address or phone).
- **Ticket management** — raising a dispute about a trip from inside the
  platform rather than Pidge's dashboard.
- **Rider Task Webhook** — for a restaurant's own captive riders on Pidge.
- **Partial delivery and route allocation** — multi-drop batching.
- **Webhook registration** — still not an API; the push URL is set on their
  side, which is why the minute sweep is the mechanism.

## Switching it on

Off by default. Nothing calls Pidge until `ENABLE_DELIVERY_DISPATCH` is true
**and** credentials exist.

```
ENABLE_DELIVERY_DISPATCH=true
ENABLE_DELIVERY_QUOTES=true   # a separate decision: pricing is not dispatching
DELIVERY_QUOTE_BASIS=max      # max | mid | min — which end of the band is charged
GOOGLE_MAPS_API_KEY=…         # accuracy + the checkout dropdown. Required for India.
                              # Enable Geocoding API and PLACES API (NEW).
GEOCODING_COUNTRY_CODES=in,ca # narrows every lookup to where you deliver
PIDGE_BASE_URL=https://store.dev.pidge.in
PIDGE_USERNAME=…
PIDGE_PASSWORD=…
PIDGE_BRAND_CODE=…            # aggregator accounts only; leave empty otherwise
DELIVERY_WEBHOOK_SECRET=…     # optional
PIDGE_TRACKING_URL=https://tracking.pidge.in/?t={code}
```

Point Pidge's webhook at `POST /api/delivery/webhook`.

## Still open

- **An aggregator account from Pidge.** Blocks per-tenant brand mapping.
- **A Google Maps key for the India deployment.** Built and wired; see
  "Where an address becomes a point" above. Without it the OpenStreetMap
  fallback answers, and measured against real Ahmedabad addresses it finds
  numbered streets and finds none of the societies, malls or crossroads that
  Indian addresses are actually written from. Until a key is set, branch
  coordinates should be pasted in by hand.
- **Coordinates for the 25 existing branches.** All 25 are empty, so their
  deliveries price from the stand-in point. `scripts/locate_branches.py`
  reports which ones a geocoder can place; the rest are a paste job in the
  admin.
- **Migration `0069` is forked.** This branch's `0069_order_deliveries` and
  `marketing`'s `0069_campaign_recipients` both descend from `0068`, and the
  shared database reads `0071`. The migration is written to tolerate the table
  already existing, but the chains still need an `alembic merge`.
