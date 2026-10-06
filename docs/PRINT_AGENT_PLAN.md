# Auto-printing: a Windows agent and a server-side print queue

A restaurant's kitchen printer should produce a ticket the moment a paid order
arrives, with nobody signed in and no browser open.

## The requirement, as given

> we need to create an agent like for windows background so if our website is
> not open and any order come then it's auto print that order … and connect
> with our server and if order come then that agent will auto print that order
> to that ipaddress connected printer

Decisions taken 2026-10-03:

| Question | Answer |
|---|---|
| Printer transport | **Both.** Network (ESC/POS over TCP) and Windows spooler; mixed across restaurants, so the installer asks. TCP is built and tested first. |
| Agent runtime | **TypeScript**, `socket.io-client`, installed as a Windows service. Same language as the three web apps, and a fifth realtime client "kept identical in behaviour" to the four that exist. |
| What prints | A new paid order (`PLACED`), a void slip on cancellation, a customer bill copy, and owner-initiated reprint / test. |

---

## The shape

The agent holds an **outbound** connection, so there is no port forwarding, no
static IP and nothing for a restaurant's router to be configured for. It is a
Windows service, so it needs neither a browser nor a logged-in user.

The decisive design choice is this: **the server owns a print queue, and the
agent pulls from it and acknowledges each job.** The agent does not print in
reaction to an event.

### Why not print on the event

Printing straight off `order:updated` breaks in five ordinary ways:

| Event | Result |
|---|---|
| Agent restarts, PC reboots | Reprints everything, or misses what arrived while it was down |
| Socket reconnects after a blip | `realtime.ts` reports a reconnect as "anything may have changed" and refetches — so it reprints |
| Printer out of paper at 21:00 | The ticket is **lost**; the kitchen never learns the order exists |
| Agent prints, then dies before telling the server | Reprint or silent miss, depending on timing |
| Owner installs the agent on a second PC | Both print, or neither does, and nothing says which |

With a queue:

- A job has an id, and the agent keeps a local ledger of ids it has printed. A
  redelivery is skipped and re-acked: at-least-once delivery, exactly-once
  paper.
- An unreachable printer **accumulates** work and prints it in order when it
  comes back.
- The owner sees "4 tickets pending, printer unreachable since 21:14", and
  Reprint is just another row.
- The socket event becomes what it already is everywhere else in this codebase:
  a hint that says *come and look*, never the data itself.

### Why the agent gets its own identity

`UserRole.KITCHEN` exists because advancing an order was `require_owner`, so
"the only way to put a board in a kitchen was to leave the owner signed in on
it — one token that also edits the menu, spends marketing budget and reads
revenue, on a tablet on a wall."

A print agent is the same argument one step further: its credential sits
unattended on a PC for years. So it is a device, not a person.

- **Paired by a six-digit code** read off the admin screen, single-use, ten
  minute expiry. Nobody copies a secret into a config file.
- Token stored **hashed**, with `token_version` for instant revocation —
  mirroring `users`.
- Scope is **one branch**, server-side. Out-of-scope is **404, not 403**, for
  the reason the order board already gives: a client learns nothing about an
  order that is not its own, including whether it exists.
- It can read its own jobs and acknowledge them. It cannot advance an order,
  read revenue or touch a menu.

### Why the receipt renders on the server

The server produces a structured document; the agent only turns it into bytes
for its own paper width.

1. **Half-and-half.** Those rules already live in three places that must agree,
   "because a disagreement means the customer sees one price and is charged
   another". A receipt rendered in the agent would be a fourth implementation,
   and a wrong half-and-half docket is a kitchen making the wrong pizza.
2. **Time.** A ticket shows the branch's timezone. An agent using the PC's
   clock prints wrong times whenever that clock drifts, and nobody notices for
   weeks.
3. Customization labels, currency and scheduled-slot wording exist
   server-side already. One place to change the ticket, for every tenant.

The document is **stored on the job**, so a reprint reproduces exactly what the
kitchen first saw even if the order or the menu has changed since.

---

## Schema — `0074_print_agents`

RLS is enabled in the migration itself, which `0070_channel_connections`
established as "the shape every new table should follow, because it is the only
way a fresh environment comes up closed".

**`print_agents`** — one row per installed PC.

`restaurant_id` and `restaurant_location_id`, both NOT NULL, the location tied
to the restaurant by a **composite foreign key onto `(id, restaurant_id)`** —
the device `ck_users_kitchen_assignment` uses, so an agent pinned to someone
else's branch is unrepresentable rather than merely unlikely. Location is not
nullable here, unlike a KITCHEN account: a printer is physically in one room.

Plus `name`, `token_hash`, `token_version`, `agent_version`, `last_seen_at`,
`is_enabled`.

**`printers`** — one row per printer an agent can reach.

`print_agent_id`, `name`, `transport` (`TCP` | `WINDOWS`), `host` / `port`,
`windows_printer_name`, `paper_width_chars` (32 for 58mm, 48 for 80mm),
`copies`, `docket_kinds`, `is_enabled`, `last_error`.

A CHECK makes the transport exhaustive — TCP demands a host, WINDOWS demands a
printer name — so a half-configured printer cannot exist in the table.

`docket_kinds` is how one PC drives two printers: the kitchen printer takes
dockets and voids, the counter printer takes bills. Routing is data, not a
branch in the agent.

**`print_jobs`**

`printer_id`, `order_id`, `kind` (`KITCHEN_DOCKET` | `CUSTOMER_BILL` |
`VOID_SLIP` | `TEST`), `source` (`AUTO` | `MANUAL`), `status` (`QUEUED` |
`CLAIMED` | `PRINTED` | `FAILED`), `document` JSONB, `attempts`, `last_error`,
`claimed_at`, `printed_at`.

**Idempotency is a partial unique index, not application logic:**

```sql
CREATE UNIQUE INDEX uq_print_jobs_auto_once
  ON print_jobs (printer_id, order_id, kind)
  WHERE source = 'AUTO' AND status <> 'FAILED';
```

A double-firing enqueue physically cannot write a second docket. Manual
reprints are `source = 'MANUAL'` and unconstrained. Same instinct as the
customer-uniqueness partial indexes in `0036`: put the rule where it cannot be
bypassed.

---

## Two flags, deliberately separate

`enable_auto_print` gets its **own** after-commit listener in
`services/print/outbox.py`, modelled on `realtime/outbox.py` but independent.
Coupling it to `enable_realtime` would mean a restaurant cannot have printing
without realtime, or the reverse. Same guarantees — queued on `session.info`,
flushed after commit, dropped on rollback, never raises — separate decision.

With the flag off, jobs are **enqueued and visible in the admin** but never
delivered: the dry run an owner can inspect, which is exactly
`enable_marketing_dispatch`'s posture and for the same reason. Paper and a
kitchen's attention are not recallable.

---

## The job document

```json
{"width": 48, "lines": [
  {"t": "text", "v": "Order BB-1042", "bold": true, "size": "double"},
  {"t": "rule"},
  {"t": "item", "qty": 2, "name": "Margherita",
   "mods": ["Left: Olives", "Right: Jalapeno"]},
  {"t": "cut"}]}
```

Structured rather than final bytes, so one document drives both an ESC/POS
socket and the Windows spooler, and the agent owns only the byte dialect. It
also makes the server's tests assertions about a document and the agent's
tests assertions about bytes, rather than both about a blob.

---

## Protocol — four endpoints, outbound only

| Endpoint | Does |
|---|---|
| `POST /print-agents/pair` | Six-digit code to agent token. Single use, ten minutes. |
| `GET /print-agents/me/jobs` | QUEUED jobs plus the current printer config; marks them CLAIMED under a two-minute lease. Config travels with the poll, so changing paper width needs no reinstall. |
| `POST /print-agents/me/jobs/{id}/ack` | `PRINTED` or `FAILED` with an owner-readable sentence. Idempotent. |
| `POST /print-agents/me/heartbeat` | `last_seen_at`, agent version, printer reachability. |

The lease needs no sweeper: a `CLAIMED` job older than two minutes is simply
claimable again on the next read. An agent that dies mid-print hands the ticket
back by doing nothing.

Socket.IO joins `location:{id}` and treats `order:updated` as *poll now*,
nothing more. The poll runs every 15 seconds as the safety net — the socket
covers latency, the poll covers the socket being down. Same division as the
kitchen board's 30s / 6s.

---

## The riskiest unknown

Printing **raw** through the Windows spooler from Node has no clean path:
`Out-Printer` is text only, a printer share needs the right sharing setup, and
FFI into `winspool.drv` is fragile. ESC/POS over TCP is a socket write and
cannot really go wrong.

So P1 ships TCP only and the spooler is spiked separately, rather than letting
the hard transport hold up the restaurants whose printers have an address.

---

## Phases

**P1 — the thing working.** Schema, renderer, queue, enqueue on `PLACED`, the
agent with TCP transport, pair / poll / ack, and an admin Printers page with
Test print.

**P2 — the rest of the triggers.** Void slip on cancellation, Reprint, the
customer bill copy, per-printer routing.

**P3 — the long tail.** Windows spooler transport, installer polish,
out-of-paper status, offline alerting.

---

## Verification

- Backend `unittest`: renderer golden files — half-and-half above all, plus a
  scheduled slot, COD against paid, and a non-rupee tenant; the job state
  machine; lease expiry; **a test that the unique index really does block a
  second automatic docket**; and that agent A gets 404 for branch B's jobs.
- `backend/scripts/dryrun_print.py`, rendering a real order to stdout — the
  idiom `dryrun_whatsapp.py` already established here as the fastest way to
  see what somebody actually gets.
- Agent: vitest against a fake `net.Server` that records bytes, with golden
  ESC/POS files, and a fake server for the poll/ack loop.
- Then a real print, which is the only test that counts.

## Known gap at the time of writing

`CLAUDE.md` says "new migrations take `0072+`". That is stale: `0072_order_charges`
and `0073_restaurant_brand` exist, so this one is `0074`. Worth correcting there
once this lands.
