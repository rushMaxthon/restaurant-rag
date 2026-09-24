# frontend-kitchen

The order board a kitchen runs on: a tablet on a wall showing what has been
ordered and what stage it is at, with one button per ticket.

## Why it is its own app

Advancing an order used to be `require_owner`, so the only way to put a screen
in a kitchen was to leave the owner signed in on it — the same token that edits
the menu, spends money on marketing campaigns and reads revenue, on a device
anyone walking past can pick up. The `KITCHEN` role (migration
`0071_kitchen_staff`) is the narrow alternative, and this app is what it signs
into.

It is not a page in `frontend-admin` because it is a different posture: one
screen, no navigation, read at arm's length by someone holding a pan. And it is
not TanStack Start like `frontend-customer` because a logged-in board has no
SEO, no link previews and no anonymous first paint — server rendering would be
cost with no benefit.

## Running it

```bash
npm run dev          # port 5175, pinned — the API's CORS list names it
npm run build        # tsc -b && vite build
npm run test         # vitest, the board rules
npm run lint
```

The API must be running at `http://localhost:8000`. Ports 5173 (customer),
5174 (admin) and 5175 (kitchen) are all in the backend's default CORS list and
all three dev servers pin their own port, so the list stays true.

## Getting an account

A kitchen login is created by an owner or an admin, not by self-registration:

```bash
curl -X POST http://localhost:8000/api/kitchen-staff \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"full_name":"Night Cook","email":"cook@example.com",
       "password":"kitchen-pass-1","restaurant_location_id":"<branch uuid>"}'
```

Omit `restaurant_location_id` and the account sees every branch of the
restaurant. An ADMIN must also send `restaurant_id`, because an admin has no
restaurant of their own.

## The rules that are easy to break

**The server decides what this screen may touch, not this screen.**
`resolve_order_board_scope` in `backend/app/services/auth.py` answers "which
restaurant, which branch" for all three roles, and both the order list and the
status write go through it. A kitchen account pinned to a branch cannot read or
advance another branch's order even with its id — `ck_users_kitchen_assignment`
and a composite foreign key make the assignment itself unforgeable. Anything
this app hides is a convenience.

**One step, and the server names it.** `ORDER_STATUS_FLOW` is strictly linear
and `PATCH /orders/{id}/status` refuses anything that is not the single legal
next status. `nextStatus` in `src/lib/board.ts` mirrors it so the button can
carry the right verb, but it is not a second opinion — when the two disagree
the server is right and its sentence is shown on the ticket.

**"Live" is a poll.** There is no WebSocket or SSE anywhere in this backend.
Four queries, one per column, every six seconds, with
`refetchIntervalInBackground` on because a board on a wall is never the focused
window. When any column fails the header says "Not updating" rather than
letting a stale rail look current.

**The first poll must not sound the alarm.** Every ticket is new against an
empty set, so `Board.tsx` records the first successful poll without announcing
it. Otherwise opening the board mid-service plays a chime for the whole rail.

**A ticket shows the food, not the invoice.** No prices, no payment method, no
delivery address — a cook does not need them and the address is somebody's home
on a wall. `src/lib/board.ts` is where that judgement lives, and it is tested.

**A pickup order passes through `OUT_FOR_DELIVERY` too**, because the backend
runs one flow for both. Naming the status on the button would tell someone
packing a collection order that it is out for delivery, so `advanceLabel`
words it by fulfillment type instead.

## The look

Dark, because a kitchen is bright and the screen sits at an angle — white
tickets on a dark rail hold contrast under overhead light and the reverse
glares. Colour carries meaning and nothing else: orange is "do this next",
amber and red are "this has waited too long", green is "done". A ticket that is
merely normal gets no colour at all, which is what makes the ones that do get
it readable at a glance.

**Urgency never tints the card border.** It did at first, and on a real board
that meant every card had a red outline — during service most tickets are past
their threshold, and a signal that is always on is not a signal. The border
stays neutral; the 3px leading stripe carries both stage and wait: the
column's own tone when calm, amber at the warning point, red when overdue. A
late ticket lifts a shade off the rail rather than being outlined.

The scan order is **order → time → items → action**, and the card follows it
exactly. Quantity is the heaviest thing on the ticket and always in the same
column, because on a busy rail it is the first thing anybody looks for.

**Three things the reference design showed that this cannot honestly render.**
`OrderFulfillmentType` is DELIVERY or PICKUP, so there is no dine-in and no
table number. `OrderItemResponse` carries no `is_veg`, so there are no
veg/non-veg dots — one guessed from a dish name is exactly the kind of claim
that gets a plate sent back. And the kitchen status chip shows the branch's own
`is_open` rather than an OPEN/BUSY/PAUSED mode, because this app has nothing to
set such a mode with and a control that only pretends to work is worse than
none.

The `HIGH` / `URGENT` badges ARE real, but derived: this backend has no
priority column, and what a kitchen means by urgent is "this has been sitting
too long", which is what `urgencyOf` already answers from the clock.

## Layout

```
src/
├── lib/
│   ├── api.ts           every call this app makes, which is four
│   ├── auth.tsx         the provider
│   ├── auth-context.ts  the context and hook, split for Fast Refresh
│   ├── board.ts         the rules — pure, and the only tested part
│   ├── board.test.ts
│   ├── queries.ts       polling and the advance mutation
│   └── sound.ts         the new-order chime, synthesised not fetched
│   ├── metrics.ts       the summary bar and the filters — pure, tested
│   ├── metrics.test.ts
├── components/
│   ├── Board.tsx        the rail, new-ticket detection, the minute tick
│   ├── Ticket.tsx       one order
│   └── SignIn.tsx       also where audio is unlocked
├── App.tsx              header, metrics, filters, scope — and it OWNS the
│                        board data (see below)
└── index.css            hand-written; shared tokens imported first
```

**The shell owns the orders, not `Board`.** They were fetched inside `Board`
and reported up through an effect so the summary bar could count the same
rows — which never settled, because `useQueries` hands back a new array on
every render: the effect fired, set state in the shell, re-rendered `Board`,
and React ended at *Maximum update depth exceeded*. Counting during render
from one source has no such failure mode, and the metrics cannot drift from
the columns beneath them because they **are** the columns.
