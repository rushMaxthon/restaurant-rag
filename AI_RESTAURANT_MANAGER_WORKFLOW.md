# AI Restaurant Manager — How It Works, Start to Finish

A plain-English guide for anyone new to this part of the system: developers picking it up, and non-technical stakeholders who need to know what it does and what it will never do.

---

## 1. What the AI Restaurant Manager is

It is the owner-facing brain of the admin app. It does two related jobs.

**It watches the business.** In the background it looks at orders, revenue, branches, offers and customers, and surfaces things worth an owner's attention — a dish that has stopped selling, a branch that has gone quiet, a day that broke pattern. These appear as the **Insight Feed**, **Today's Briefing** and **Recommendations**.

**It answers questions.** The owner types a question in plain English — *"why are my sales down?"*, *"which branch did best last week?"*, *"is anyone paying by card?"* — and gets an answer built from their own data.

This document is mostly about the second job, the **AI Chat**, because that is where most of the recent work has gone.

The single most important design decision, and the one that explains almost every other decision below:

> **The system would rather say "I can't answer that" than give an answer that sounds right and isn't.**

A confidently wrong number in a business tool is worse than no number, because the owner acts on it. Nearly everything that follows — the routing rules, the refusals, the guardrails — exists to protect that principle.

---

## 2. The AI Chat flow chart — the complete journey of one question

Here is the whole path, from the owner typing to the answer appearing.

```
┌───────────────────────────────────────────────────────────────────┐
│                        OWNER QUESTION                             │
│              typed in plain English in the admin app              │
└───────────────────────────────┬───────────────────────────────────┘
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                       AUTHENTICATION                              │
│              Who is logged in? Not signed in → stop.              │
└───────────────────────────────┬───────────────────────────────────┘
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                  RESTAURANT / BRANCH SCOPE                        │
│      Built from the LOGGED-IN USER, never from the question.      │
│      Frozen here — nothing downstream can widen or change it.     │
└───────────────────────────────┬───────────────────────────────────┘
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│              TIER 1 — DETERMINISTIC ROUTER  (~0 sec)              │
│   Text patterns. Also reads the time period, direction, ranking,  │
│   limit and metric out of the sentence. No AI involved.           │
└───────────────┬───────────────────────────────┬───────────────────┘
                │ MATCHED                       │ NO MATCH
                │                               ▼
                │        ┌──────────────────────────────────────────┐
                │        │           PLANNER CACHE                  │
                │        │  Seen this wording before (24h)?         │
                │        │  Stores the ROUTE only — never numbers.  │
                │        └────────┬────────────────────┬────────────┘
                │                 │ HIT (~0 sec)       │ MISS
                │                 │                    ▼
                │                 │   ┌────────────────────────────────────┐
                │                 │   │  TIER 2 — QWEN PLANNER (~6-8 sec)  │
                │                 │   │  Sees: the question + tool names.  │
                │                 │   │  Returns: one tool name + settings.│
                │                 │   │  ✗ no database  ✗ no numbers       │
                │                 │   │  ✗ writes no part of the answer    │
                │                 │   └───────┬──────────────────┬─────────┘
                │                 │           │ VALID            │ INVALID /
                │                 │           │ (re-checked)     │ TIMED OUT
                │                 │           ▼                  ▼
                │                 │      (cache the route)  ┌──────────────┐
                │                 │           │             │   TIER 3 —   │
                └─────────────────┴───────────┤             │   REFUSAL    │
                                              │             │ Says plainly │
                                              │             │ it cannot    │
                                              │             │ answer, and  │
                                              │             │ why. Never   │
                                              │             │ guesses.     │
                                              ▼             └──────┬───────┘
┌───────────────────────────────────────────────────────────────┐  │
│                  TOOL / SKILL EXECUTION                       │  │
│   A fixed, hand-written reader from a closed catalogue.       │  │
│   No AI-generated SQL, ever.                                  │  │
└───────────────────────────────┬───────────────────────────────┘  │
                                ▼                                  │
┌───────────────────────────────────────────────────────────────┐  │
│                       READ DATABASE                           │  │
│   SELECT only. Nothing is written, updated or deleted.        │  │
└───────────────────────────────┬───────────────────────────────┘  │
                                ▼                                  │
┌───────────────────────────────────────────────────────────────┐  │
│           BUSINESS CALCULATIONS + SCOPE + VALIDATION          │  │
│   Every query filtered to this restaurant (and branch, if one │  │
│   was named). Changes, shares and totals computed in code.    │  │
│   Thin data flagged. Empty periods stated, not dressed up as  │  │
│   zero findings.                                              │  │
└───────────────────────────────┬───────────────────────────────┘  │
                                ▼                                  │
┌───────────────────────────────────────────────────────────────┐  │
│                      STRUCTURED FACTS                         │  │
│   Validated figures + a correct summary written by code.      │  │
│   Nothing reaches the next step until it has passed here.     │  │
└───────────────────────────────┬───────────────────────────────┘  │
                                ▼                                  │
┌───────────────────────────────────────────────────────────────┐  │
│              QWEN WRITES THE ANSWER  (~20-60 sec)             │  │
│   Gets: the owner's question + the validated facts.           │  │
│   Does: explains them in natural language, shaped to what     │  │
│         was actually asked.                                   │  │
│   ✗ no database   ✗ no SQL   ✗ no new calculations            │  │
└───────────────────────────────┬───────────────────────────────┘  │
                                ▼                                  │
┌───────────────────────────────────────────────────────────────┐  │
│                    NUMBER GUARDRAIL                           │  │
│   Every figure in the reply checked back against exactly what │  │
│   Qwen was handed. One unsupported number → the whole reply   │  │
│   is discarded and the code-written answer is sent instead.   │  │
└───────────────────────────────┬───────────────────────────────┘  │
                                ▼                                  │
┌───────────────────────────────────────────────────────────────────┐
│                    RETURN ANSWER TO OWNER                         │
│               streamed back into the chat panel                   │
└───────────────────────────────────────────────────────────────────┘
```

**The division of labour, which is the whole design:**

> **The backend owns truth. Qwen owns wording.**

| | |
|---|---|
| 🚫 | **Qwen does not touch the database.** It never sees a table, never writes SQL, and never runs a query. It is handed facts that were already fetched and checked. |
| 🚫 | **Qwen does not produce numbers.** Every figure it may use is given to it. It is told not to calculate, estimate or extrapolate — and anything numeric it writes is verified afterwards. |
| 🚫 | **Qwen cannot change scope.** Which restaurant and branch were decided from the login, long before the model was involved. |
| 🔒 | **Tools are read-only.** Answering a question can never change data. |
| ✅ | **Final numbers come from the database.** Computed in code, verified in code. |
| ✍️ | **Qwen writes the reply the owner reads** — from the question and those validated facts, and nothing else. |

Two things in that chart are easy to miss and matter enormously:

**Scope is decided before routing.** By the time anything looks at the question's words, the system has already fixed *whose data* may be read, based purely on the logged-in user. Nothing in the question text can change it.

**Facts are validated before the model sees them.** Qwen is never asked to make something out of nothing. A refusal, a failed tool, or a period with no trade never reaches it — there is nothing truthful to say, so the safe answer goes out as written. The model is only ever handed facts that are already correct, and asked to explain them well.

---

## 3. The three tiers

### Tier 1 — Deterministic rules (the fast path)

A library of text patterns. If the question matches one, the system knows exactly what to run. No AI involved.

- **Speed:** effectively instant (0.00 seconds in live testing)
- **Reliability:** identical answer for identical question, every time
- **Coverage:** the large majority of real questions

### Tier 2 — The LLM planner (the flexible path)

Only reached when no Tier 1 rule matched. A local language model (Qwen) is given the question and a catalogue of the available tools, and asked one question: *which tool answers this, and with what settings?*

- **Speed:** about 6–8 seconds when the model is warm
- **What it does:** picks a tool. That is all.
- **What it does not do:** write SQL, or see any data

Its choice is validated before use. If it names a tool that does not exist, or gives arguments that do not fit, the plan is thrown away.

Note that this is a **different call** from the one that writes the answer (§9a). This one chooses; that one explains. They are deliberately separate, so a question that routes perfectly by rule still gets a natural reply, and a routing failure never becomes a wording failure.

### Tier 3 — Honest refusal (the safety net)

When neither tier can answer, the system says so and explains why. It does not guess, does not substitute a related metric, and does not quietly answer a different question.

Two different kinds of "no":

| | Example | Reply |
|---|---|---|
| **Data does not exist** | *"how profitable was last month?"* | Says food and operating costs are not recorded anywhere in the system |
| **Data exists, question unclear** | very unusual phrasing | Says it could not work out what was being asked |

---

## 4. The 28 tools — what each one does

A **tool** is a small, fixed, read-only reader of the database. Each has a name, a description, and a strict list of allowed settings. There is no way to invent one at runtime.

### Fixed tools, dynamic answers

This is the point most often misunderstood, so it is worth stating directly.

**The tool is fixed. The answer is not.**

Each tool is a hand-written query that never changes: *"count this restaurant's orders in this period, grouped by payment method."* That query is reviewed, tested, and identical on every run. What changes is **the data it lands on**. Ask the same question tomorrow and the same tool runs — but it reads whatever is in the database at that moment, so the numbers are today's.

So:

- **Fixed** — which tables are read, how the figures are calculated, what the tool is allowed to touch
- **Dynamic** — the actual numbers, which are read live from the database on every single request
- **Never cached** — no answer or figure is stored and replayed. Only the *routing decision* is cached (§11), never the data

An owner never sees a stale number, and a developer never has to wonder whether a query changed shape between two runs.

### The common execution flow — the same for all 28

Every tool runs through exactly this path. There is no per-tool special case, no bypass, and no second way in.

```
   A tool name + settings arrive
   (from Tier 1 rules, or from the Qwen planner)
              │
              ▼
   1. LOOK UP the name in the closed registry
      Not in the list → rejected. Nothing runs.
              │
              ▼
   2. VALIDATE the settings against that tool's own schema
      Wrong or unexpected settings → rejected, not guessed at.
              │
              ▼
   3. INJECT the scope
      Supplied by the caller from the login.
      A tool can never be told which restaurant to read.
              │
              ▼
   4. RUN the hand-written, read-only query
      SELECT only, always filtered to that scope.
              │
              ▼
   5. RETURN plain data — numbers, rows, labels
      Errors are RETURNED, not thrown: one broken tool
      cannot bring down the whole request.
              │
              ▼
   6. CODE formats it into the sentence the owner reads
```

Step 3 has a hard guarantee behind it. No tool may declare a setting like `restaurant_id`, `location_id`, `customer_id`, `sql` or `query` — and this is checked **when the application starts**, not in a test. A tool that would let its caller pick whose data to read cannot even load; the app refuses to boot.

### What each tool reads and answers

**Headline numbers — how is the business doing?**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_period_metrics` | Orders for this period and the one before | Overall totals and how they moved | *"how did last week go?"* |
| `get_metric_deltas` | The same orders, as changes | Which headline numbers are up or down | *"what's changed this month?"* |
| `get_daily_series` | Orders grouped by trading day | Day-by-day shape and quiet days | *"show me daily sales"* |
| `get_data_coverage` | Order, day and customer counts | Whether there's enough trade to trust a percentage | *(used to caveat other answers)* |

**Why did something change?**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_breakdown` | Orders and order lines, split by item, category, hour, daypart, weekday, customer type or branch | What actually drove a rise or fall | *"what's behind the drop?"* |
| `get_anomalies` | Daily revenue against the recent baseline | Days that broke pattern | *"was any day unusually bad?"* |

**Branches**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_location_performance` | Orders grouped by branch, this period vs last | Which branches are up, down, or have stopped trading | *"how are my branches doing?"* |
| `get_branch_metrics` | Orders for one named branch | How a single branch is performing | *"how is Bodakdev doing?"* |
| `compare_locations` | Orders for two named branches, same period | Which of two branches is doing better | *"Bodakdev vs Satellite?"* |
| `get_branch_status` | Branch settings: open state, closure reason, hours, fulfilment options, minimum order | Whether a branch is actually open and taking orders | *"is any location shut?"* |

**Menu**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_menu_health` | Menu items and categories per branch, with prices and availability | What's on the menu, and gaps between branches | *"how many menu items do I have?"* |
| `get_stockouts` | Records of when dishes were switched off | Which dishes were unavailable, and for how long | *"was anything out of stock?"* |
| `get_combos` | Item pairings found in real baskets | What customers buy together | *"what sells well together?"* |

**Orders and operations**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_order_operations` | Order timestamps | How long orders take to accept and prepare | *"how fast are we serving?"* |
| `get_cancellations` | Cancelled orders and their recorded reasons | Why orders are being cancelled and what it costs | *"why are orders cancelled?"* |
| `get_fulfillment_mix` | Orders by delivery type and timing | Delivery vs pickup, ASAP vs scheduled | *"what's my delivery vs pickup split?"* |
| `get_schedule` | Branch opening hours, future-order settings and fulfilment slots | When and how far ahead customers can order | *"how far ahead can people order?"* |

**Money and payments**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_payment_mix` | Orders by payment method | How customers pay | *"is anyone paying by card?"* |
| `get_payment_failures` | Orders that never completed payment | Money lost at checkout — recoverable, unlike lost demand | *"how many orders failed at payment?"* |
| `get_payment_health` | Payment provider transactions and failure codes | Whether the payment provider is the problem | *"are card payments failing?"* |
| `get_order_economics` | Delivery fees, tax and discounts on orders | Where the gap sits between subtotal and what the customer paid. **Explicitly not profit** — food and operating costs are recorded nowhere | *"what makes up my order totals?"* |

**Customers and marketing**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_customer_cohorts` | Orders grouped by new vs returning customers | Whether customers come back | *"are people ordering again?"* |
| `get_notification_campaigns` | Push campaigns with sent, delivered, opened and failed counts | How push messaging performed | *"how did my notifications do?"* |

**Offers**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_offer_catalogue` | Both offer tables — template and AI-generated — with state and expiry | Which offers exist and which are actually live | *"what offers are live?"* |
| `get_offer_performance` | Offers alongside the orders that used them | How offers did — **observational**, it reports what happened, it does not claim the offer *caused* it | *"did my offers work?"* |

**What the system has already said**

| Tool | Reads | Answers | Example question |
|---|---|---|---|
| `get_recent_briefing` | The latest generated briefing | What the morning briefing said | *"what did you tell me today?"* |
| `get_insight_history` | Findings already shown and not dismissed | What has been flagged recently | *"what findings have been raised?"* |
| `get_open_recommendations` | Recommendations awaiting a decision | What is waiting on the owner | *"what needs my approval?"* |

---

## 5. The skills

A **skill** is a level above a tool. Where a tool fetches one specific thing, a skill answers a whole owner question — often pulling several pieces together and writing a proper explanation.

There are 15:

| Skill | Answers questions like |
|---|---|
| `revenue_diagnosis` | *"why are my sales down?"* — the flagship: what changed, and what drove it |
| `metric_lookup` | *"how many orders last week?"* |
| `item_performance` | *"which dishes sell best?"*, *"what's falling?"* |
| `time_patterns` | *"when am I busiest?"* |
| `customer_retention` | *"are customers coming back?"* |
| `offer_performance` | *"did my offers work?"* |
| `recommendations` | *"what should I do?"* |
| `briefing_recall` | *"what did you tell me this morning?"* |
| `cancellation_reasons` | *"why are orders being cancelled?"* |
| `order_operations` | *"how fast are we serving?"* |
| `action_outcomes` | *"did the thing I approved actually help?"* |
| `item_promotion_advice` | *"which dish should I promote?"* |
| `branch_comparison` | *"how does Bodakdev compare to Satellite?"* |
| `tool_answer` | the wrapper that runs a single tool and formats its result |
| `unsupported` | the honest refusal |

Where a skill and a tool overlap, **the skill wins** — it gives a fuller answer and it is faster.

---

## 6. How deterministic routing works

Tier 1 is a set of text patterns, and the interesting engineering is in what it does *not* do.

**It reads more than the topic.** From one sentence it also extracts:

- **The time period** — *"yesterday"*, *"last week"*, *"last 30 days"*, *"this month"*. Worked out in code, in the restaurant's own timezone, because a made-up date range would silently answer a different question than the one asked.
- **The direction** — top or bottom, rising or falling
- **What to rank by** — revenue, order count, or quantity
- **A limit** — *"top 3"* means three
- **The metric** — revenue, orders, customers, items, average order value

**It gives each tool only the settings that tool accepts.** Settings come from each tool's own definition. This was a real bug: every routed tool was being handed a time window, but `get_insight_history` takes a *count* instead. The question routed perfectly and then failed validation, and the owner saw *"I could not look that up"* — which is indistinguishable from the feature not existing.

**It has no defaults.** If a question asks about a metric the system can't identify, it does not fall back to revenue. Silently substituting is exactly the failure mode this design exists to prevent.

**It separates questions that look almost identical.** Some real pairs it now gets right:

| Question | Goes to | Because |
|---|---|---|
| *"how far ahead **can** people order?"* | `get_schedule` | asking about a **setting** |
| *"**do** customers schedule in advance?"* | `get_fulfillment_mix` | asking about **behaviour** |
| *"are **card payments** failing?"* | `get_payment_health` | the provider |
| *"how many **orders** failed at payment?"* | `get_payment_failures` | lost orders |
| *"what offers are **live**?"* | `get_offer_catalogue` | which exist |
| *"did my offers **work**?"* | `get_offer_performance` | how they did |
| *"was anything **out of stock**?"* | `get_stockouts` | dishes switched off |
| *"how much stock did I **waste**?"* | refusal | wastage isn't recorded |

**Current coverage: 19 of the 28 tools have direct rules.** Of the nine that don't:

- **Six** already have a skill that answers better and faster, so a rule would only get in the way.
- **Two** are branch-specific (`get_branch_metrics`, `compare_locations`) and are handled elsewhere — see scoping below. A text pattern cannot know what your branches are called; the branch resolver can.
- **One** is rare enough that the planner is the right home for it.

---

## 7. When the planner (LLM) is used

Only when Tier 1 found nothing. In live testing, 8 of 9 real questions never reached it.

The planner gets the question and the tool catalogue. It replies with one choice. That reply is then checked: the tool must exist in the current build, and the arguments must validate. A malformed or unknown answer is discarded and the question falls through to the older skill router and then to refusal.

The reason it is kept on such a short leash is cost of error. A wrong tool choice produces a real, correctly-calculated number that answers the wrong question — the hardest kind of mistake for an owner to spot.

---

## 8. Restaurant and branch scoping

### Restaurant scoping — structural, not conversational

When a request arrives, the system builds a **scope** from the logged-in user before the question is read. An owner is pinned to their own restaurant and cannot name another, even by accident. An admin must name a restaurant explicitly.

Every database query in every tool filters on that scope. Two protections make this hard to get wrong:

1. The scope object is **frozen** — it cannot be changed after the permission check that created it.
2. No tool may accept an argument like `restaurant_id`, `location_id`, `customer_id`, `sql` or `query`. This is checked **when the application starts**, not in a test. A tool that would let its caller choose whose data to read cannot even be loaded — the app refuses to boot.

The practical effect: there is no sentence an owner could type that would show them another restaurant's data, because the question is never what decides.

### Branch scoping — resolved against real names

If a question names a branch, the system looks that name up among the restaurant's actual branches. Three outcomes:

- **No branch named** — the answer covers the whole restaurant
- **One branch named** — the answer covers that branch, **and says so**
- **A branch the user may not read** — refused outright

That middle case used to be a genuine bug: the branch name was quietly dropped and restaurant-wide figures were shown in reply to a branch question.

---

## 9. Safety and accuracy guardrails

**Everything is read-only.** No chat path writes, updates or deletes anything. Answering a question cannot change data.

**No text-to-SQL, ever.** The AI never writes a query. It picks from a fixed catalogue, and each tool's query is written and reviewed by hand.

**Numbers come from the database, not the model.** Qwen is handed figures that are already computed and checked. It is told, in the prompt, never to calculate a new one — and it is checked afterwards regardless.

**Every figure in a generated answer is verified.** After Qwen writes the reply, every number in it is matched back against exactly what the model was handed. A single unsupported figure discards the *entire* reply — not the offending sentence — because a reply that invented one number cannot be trusted about the others either. The owner then gets the code-written answer, which is built from the same facts and is always correct.

**In the background analysis path** the same idea goes further: percentages, sums and differences are recomputed and compared within tight tolerances. This was tested by deliberately corrupting outputs to confirm the checks actually fire.

**Offers are never published automatically.** The system can *propose* an offer. Turning it into something customers see always requires an explicit owner approval. This boundary has been held unchanged throughout.

---

## 9a. How Qwen writes the answer

The last step before the owner reads anything. Qwen is given two things and nothing else:

1. **The question**, exactly as the owner typed it
2. **The validated facts** — the figures the tools returned, plus the correct summary that code already wrote

It is not asked to rewrite that summary. It is asked to **answer the question**, using those facts, in whatever shape the question calls for.

### How it is told to write

Six numbered steps, in order, placed at the very end of the prompt — the last thing the model reads is how to write, rather than a template to copy:

1. **Answer in the first sentence.** No preamble, no restating the question. Asked how many orders, give the number. Asked whether to promote something, say yes or no. If the question contains a wrong assumption, correct it first.
2. **Then finish the thought.** A "why" needs the answer *and* the two or three biggest things behind it. A bare figure with no sentence around it is not an answer.
3. **Let the question pick the shape.** There is no house format — a sentence for a simple fact, a list for a ranking, structure only when it genuinely helps. Never "Summary:" / "Details:" / "Analysis:" / "Conclusion:", and never the same opening twice.
4. **Handle numbers well.** Money as an owner writes it. Two or three figures a sentence at most. Each said once. A percentage only where it carries meaning. Call a measure what the facts call it — a median is not an average.
5. **Never write "driven by", "drove", "because of", "caused by", "due to".** Those claim a cause the data cannot show.
6. **Sound like someone who knows the business** — and say what the figures *mean* for the restaurant, which is the part an owner cannot get from a table of numbers.

### The safety rules underneath

Unchanged, and each has a test asserting it is still in the prompt:

| Rule | Why |
|---|---|
| Use only the figures supplied — never estimate, extrapolate, or calculate | The backend owns arithmetic |
| Never invent information; if the facts don't answer the question, say so | A clear "I don't have that" beats a guess |
| **Absence is not a yes and not a no** | Added after a real failure — see below |
| Say when a caveat undercuts the answer | Thin data should not read as settled |
| This restaurant, this period, this branch only | Scope is not the model's to widen |
| Never mention tools, databases, queries or ids | The owner asked about their business |
| Advice comes from these facts alone | No tactics the data says nothing about |
| Don't overstate certainty | A short period is a signal, not proof |

### Presentation decisions the backend makes, not the model

Some things are too important to leave to a rule the model may ignore, so they are decided in code before the prompt is built:

- **A percentage measured against a near-zero base is withheld.** A quiet week followed by a normal one is arithmetically "up 2859.6%", which tells an owner nothing and buries the ₹1,260 that matters. Above 300%, or against a zero base, the percentage is dropped from the facts *and* from the reference answer — the model copies what it is shown, so it has to come out of both. The owner-facing fallback keeps it.
- **Counts are sent as whole numbers.** The metrics layer works in floats, so an order count arrives as `1.0` and the model wrote back "up from 1.0 orders".
- **A median reported as an average is rejected outright.** The prompt could not stop this one: asked how fast orders are served, the model repeatedly turned "a median of 0.3 minutes" into "an average of 0.3 minutes" — same figure, different statistic, and no way for an owner to tell. It now fails closed to the code-written answer. The check only fires where the facts mention a median and never an average, so a genuine "average order value" answer is untouched.

### What the model is not shown

Internal identifiers — `restaurant_id`, location ids, tool names, raw snapshots — are stripped before the prompt is built, at every level of nesting. A model that cannot see an id cannot repeat one back. This also cut the prompt for a revenue question from 21KB to 5.6KB, which on a CPU-only host is the difference between answering and timing out.

Long fact lists are capped at their top few rows. Those rows are already the ones ranked most significant, and the tail cost seconds per answer while adding nothing an owner would read.

### The failure this caught

An early live test asked *"are customers coming back?"* against data containing only a **new** customer cohort — no returning customers existed at all. Qwen answered *"Yes, customers are coming back,"* citing the new-customer revenue.

No number was invented, so the numeric guardrail saw nothing wrong. The fabrication was in the *reasoning*: absence of a returning cohort had been read as a positive answer. That is what the "absence is not a yes" rule exists for. The same question now answers: *"No returning customers were recorded during 11 Aug – 17 Aug 2026,"* and often adds the data caveat unprompted.

It is worth being clear about the limit here: a numeric guardrail cannot catch a wrong conclusion drawn from correct numbers. That class of error is managed by the prompt rules and by the fact that Qwen only ever sees pre-validated data — not by verification after the fact.

---

## 10. When data exists vs when it doesn't

**Data exists** → a real answer with real figures, always stating the period covered, and the branch if one was named.

**Data exists but the period is empty** → says so plainly: *"There were no counted orders in 11 Aug – 17 Aug 2026."* It does not report zero as if zero were a finding.

**Data exists but is too thin to trust** → percentages come with the caveat, rather than a confident-looking figure computed from four orders.

**Data does not exist at all** → a refusal that names what is genuinely missing:

| Asked about | Reply says |
|---|---|
| Profit, margins, food cost | Costs are not recorded anywhere in the system |
| Reviews, ratings | No review data is collected |
| Stock levels, wastage | Knowing when a dish was switched off is not the same as knowing stock |
| Staff, shifts, labour | Not recorded |
| Competitors, market share | The system only sees this restaurant |
| Marketing spend | Spend isn't recorded — **but campaigns are**, and the reply points there |
| Reservations, refunds, delivery partners | Not recorded |

That marketing case is a good illustration of the standard. Campaigns exist and carry delivered and opened counts; spend does not exist at all. Blurring the two would either invent a cost or hide real data. So it refuses the spend and names the campaigns.

---

## 11. Caching

Only **planner decisions** are cached — the mapping from a question's wording to the tool that answers it. Never the answer itself, and never any figures.

- The key is the normalised question text, so *"Why are my sales down?"* and *"why are my sales down"* share an entry
- Entries last 24 hours
- A cached plan is **re-validated on the way out** — never trusted just because it was stored, since the tool set can change between writing and reading
- A version stamp is bumped whenever the tools or the prompt change, so old mappings cannot outlive what they mapped onto

The effect: an owner asking their usual questions gets instant answers even on phrasings that originally needed the planner. And because only the *route* is cached, a repeat question always re-reads the database — yesterday's numbers are never served for today.

---

## 12. Rollout and feature flags

Each capability has two independent switches, and the order matters.

1. **A global flag** — does this path exist in this build at all?
2. **A restaurant allowlist** — who currently sees it?

An empty allowlist means everyone. So widening a rollout is *deleting a line* rather than editing logic, and narrowing it back is adding one.

There are two such pairs, deliberately kept separate:

| Capability | Controls |
|---|---|
| **Tool path** (Tier 2 planner) | Whether a model may *choose* which data is read |
| **Answer generation** | Whether Qwen *writes* the reply the owner reads |

Choosing a tool and writing an answer are different risks, so they can be rolled out, and rolled back, independently. Answer generation also has its own flag rather than reusing the existing narration flag — that one governs the **briefing** as well, and reusing it would have silently switched on owner-facing briefing narration as a side effect. Two audiences, two switches.

With answer generation off, chat still works end to end on the code-written answers.

Any restaurant outside the rollout still gets the full Tier 1 skills and Tier 3 refusals. The flag gates *extra capability*, never correctness — a fix behind a flag would mean the wrong answer is still live for everyone else. That exact leak was found and closed: the fallback path was re-running the rules without carrying the rollout decision with it, which quietly became a way around the flag.

The background AI analyst has its own separate flags, and remains in **shadow mode** — it runs and logs, its findings are recorded for review, and owners do not see them.

---

## 13. What happens when things go wrong

**A tool fails.** Failures are returned, not thrown. One broken tool cannot abort the whole request, and the failure is logged with enough detail to fix.

**The planner produces nonsense.** Discarded at validation. Falls through to the older router, then to refusal.

**The planner is slow or times out.** Times out at 45 seconds and falls through. The owner waits, but still gets an answer from the rules path.

**Qwen fails to write the answer.** Times out, returns malformed output, writes an over-long reply, or uses a number it was not given — all lead to the same place: the code-written answer, which is built from the same validated facts and is always correct. The owner still gets a correct reply; it just reads more mechanically. Every fallback is logged with its reason, because falling back is invisible to the owner and that log line is the only way anyone finds out the model is failing.

**There are no facts to write from.** The model is not called at all. Nothing validated to say means nothing to explain, and handing an empty pack to a model is an invitation to fill the silence.

**An unknown skill name is produced.** Falls back to the revenue diagnosis — a broadly useful answer beats an error page.

**The question is genuinely unsupported.** Tier 3 refusal, naming what's missing.

**A branch is named that the user may not read.** Refused, not silently widened to the whole restaurant.

---

## 14. Current limitations and known issues

**Latency is the weak point, and it is now the main one.** The Ollama host is CPU-only and generates about **3 tokens per second**. A generated answer takes roughly **20–60 seconds**, against effectively zero for a code-written one. Routing is still instant; the wait is the writing. On a machine with a GPU this largely disappears — nothing in the design needs changing, only the hardware. Until then it is a real cost that buys a much better-reading answer, and it is why the rollout is one restaurant at a time.

**Answer length is capped by that same limit.** Replies are capped at ~1,100 characters, because a longer one could not finish before the timeout. Answers that would genuinely benefit from more detail get the shorter version.

**A wrong conclusion from correct numbers is not caught automatically.** The guardrail verifies figures, not reasoning. The "are customers coming back?" failure in §9a is the shape of it. Prompt rules and pre-validated facts manage this; verification after the fact mostly cannot.

**One known misreading is still open.** Asked *"how fast are we serving orders?"* where the only recorded measure is **time to accept** — preparation timings were never recorded — the model answers about serving. The statistic swap (median → average) now fails closed, which catches this particular case as a side effect, but the underlying confusion of one measure for another is not something a deterministic check can catch in general. If an owner asks about a measure that does not exist, the code-written answer says so plainly; a generated one may not.

**Streaming is not token-by-token.** The answer is produced whole, checked, then chunked to the screen — so the owner waits through the full generation before text starts appearing. Streaming tokens live would mean showing text before the guardrail had seen it, and an invented figure cannot be recalled once it has been read.

**The background AI analyst is still in shadow mode.** It runs, its findings are validated and logged, and owners do not see them.

**Some data is reachable but deliberately not exposed.** Individual customer chat history, for instance, is a privacy decision nobody has signed off, so no tool reads it.

**Coverage is broad but finite.** Twenty-eight tools and fifteen skills cover a great deal, but a question about something genuinely not recorded gets a refusal. That is working as intended, not a gap to be patched with a guess.

**One long-standing test failure** in the combos generation area, unrelated to chat routing, still fails. Everything else passes — **725 of 726 tests**.

---

## 15. Worked examples

These are real answers from a live run, not illustrations.

### *"Why are my sales down this week?"*

1. Scope fixed to the owner's restaurant from their login
2. Tier 1 matches immediately → `revenue_diagnosis`, last 7 days
3. The skill pulls this period against the last and attributes the change across dishes, categories, times and customer groups
4. Facts validated; code writes a correct summary
5. Qwen gets the question and those facts
6. Every figure in its reply checked back against them

**Answer:** *"Your sales are **up** this week, not down. Revenue grew to **₹1,304** from **₹44** in the previous period, a **2859.6% increase**. The biggest contributors were new customers (**₹1,144**), afternoon sales (**₹1,046**), main course items (**₹436**), and Pad Thai Veg (**₹304**)."*

Worth noting: it **corrected the false premise in the question**. The old code-written answer stated the same figures but could not tell the owner they had asked about a fall that didn't happen.

### *"Are customers choosing delivery or pickup more?"*

1. Tier 1 → `get_fulfillment_mix`
2. Tool reads this restaurant's orders only
3. Qwen explains the split

**Answer (~33 sec):** *"Customers are choosing pickup more. In the period 11 Aug – 17 Aug 2026, 60.0% of orders were pickup, compared to 35.0% delivery."*

### *"Are customers coming back?"*

The facts contain a **new** customer cohort and no returning one.

**Answer:** *"No returning customers were recorded during 11 Aug – 17 Aug 2026. The ₹1,144 revenue came from 18 new customers, up from ₹0 in the previous period. However, the data is limited due to few trading days and low order volume."*

It refused to read absence as a yes, and volunteered the caveat.

### *"how much did I spend on marketing?"*

1. Tier 1 matches the marketing-spend refusal pattern
2. No tool runs, no database query, **and Qwen is never called** — there are no facts to explain

**Answer (~0 sec):** *"No marketing or advertising spend is recorded anywhere, so I cannot tell you what it cost or what it returned. I can show you the push campaigns you have sent and how many were opened."*

### *"how is Bodakdev doing?"*

1. The branch resolver checks "Bodakdev" against this restaurant's real branch names
2. It matches and is permitted, so the scope narrows to that branch
3. The skill runs against that branch alone; the reply states which branch it covers

### *"which dishes are never bought together?"* (unusual phrasing)

1. No Tier 1 rule matches → Tier 2 planner picks `get_combos`
2. Choice validated, tool runs, facts validated
3. Qwen writes the answer

The route is cached, so the *planner* step is skipped next time — the writing step still runs, because the data may have changed.

---

## In one paragraph

The owner asks a question in plain English. The system decides whose data may be read from *who is logged in*, never from the question. Fast pattern rules pick the right tool instantly; a small local model steps in only when the phrasing is unusual. The tool reads the database — read-only, filtered to that one restaurant — and code computes and validates every figure. Only then is Qwen brought in, handed the question and those validated facts, and asked to explain them naturally; it never touches the database, never produces a number, and is checked afterwards against exactly what it was given. When the data isn't there, the system says so and names what's missing. **The backend owns truth; the model owns wording** — and if the model fails at wording, the owner still gets the truth.
