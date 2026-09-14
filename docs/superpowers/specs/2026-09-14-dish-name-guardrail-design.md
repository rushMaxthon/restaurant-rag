# Dish-Name Guardrail — Decide by Distance, Not by Word Lists

**Status:** approved in conversation, 2026-09-14
**Surface:** `backend/app/services/rag.py` — intent resolution
**Related:** the bugs this closes are recorded in commits `e65b9c7` ("today") and
`29a0813` ("special"/trending)

---

## Why

Two bugs, three weeks apart, one cause.

> **"What is menu for today?"** → *"We don't have a specific 'today' menu…"*
> **"Which item are trending?"** → *"We don't have a 'special' item on the menu…"*

Both are the assistant telling a customer that a word they used is not on the
menu. Nothing was wrong with retrieval and the model was not hallucinating: it
was answering the question it was handed. The parser had decided that "today"
and "special" were dish names, searched for them, found nothing, and every stage
after that behaved correctly on a false premise.

## The mechanism that produces this

The dish extractors **never look at the menu**. Checked: `_canonicalize_topic`,
`_extract_bare_topic_hint` and `_extract_direct_item_hint` contain zero
references to `MenuItem`, to a query, or to a database session. They are pure
string manipulation.

They decide by **elimination** — strip the words known not to be food, and
whatever survives must be a dish:

```
"What is menu for today?"  → drop what/is/for → drop "menu" → "today"    → dish
"whats special"            → drop whats       →              → "special"  → dish
```

That is a blocklist: `QUERY_STOPWORDS`, `TOPIC_STOPWORDS`, `BARE_TOPIC_STOPWORDS`,
maintained by hand. Every generic word not yet on a list becomes a dish name.

This cannot converge. The set of things people say that are not dish names is
unbounded; the set of things that ARE dish names is 189 rows in Postgres. The
blocklist has already been extended twice in this codebase — time words after
"today" — and `there` and `want` are still unfixed, surviving into topics as
"there breakfast" and "want momo".

## What this is not

- **Not another word list.** Adding "special" and "trending" fixes two phrasings
  and leaves the mechanism intact. The explicit requirement for this work was
  that it must understand the sentence, not match exact words.
- **Not an output guardrail.** Checking the reply for "we don't have 'X'" would
  mean pattern-matching phrasing — the word-based approach again — and would
  spend a model call producing an answer we then discard. The failure is a
  branch taken three steps earlier, not a malformed reply.
- **Not a change to what happens when no dish is named.** That path already
  exists and already works.

---

## The signal, measured

`_retrieve_candidates` already computes cosine distance from the message to all
189 menu embeddings on every turn. The nearest distance answers "is anything on
this menu close to what they said" — and it is currently discarded. This is the
missing relevance threshold: today there is no cutoff anywhere, so a nonsense
query still returns 8 dishes, just the 8 least-bad ones.

Measured over 39 phrases, `nomic-embed-text`, against the seeded 189-item menu:

| Group | min | max |
|---|---|---|
| Dish on the menu | **0.135** | **0.271** |
| Dish, misspelled | 0.210 | **0.376** |
| Craving, no dish named | **0.372** | 0.569 |
| Generic word, not food | 0.446 | 0.555 |
| Food not on this menu | 0.387 | 0.507 |
| Not food at all | 0.522 | 0.574 |

**A single threshold at ≈0.38 separates "a dish is named" from everything else.**
Misspellings land on the correct side (max 0.376), which matters because
`0055_menu_item_trigram_search` exists for exactly that case.

No word is named anywhere in this. "Today" is rejected because nothing on the
menu is near it, not because it appears on a list — and so is every generic word
nobody has thought of yet. That is the property this design exists for.

### Correction to an earlier claim

In conversation I proposed three tiers, with a middle band distinguishing *food
we do not serve* ("sushi") from *not a food request* ("trending"), so the
honest "we don't have sushi" could be kept. **The wider measurement does not
support that.** Food-not-on-menu spans 0.387–0.507 and sits entirely inside the
generic band (0.446–0.555). Distance cannot tell "sushi" from "trending".

That capability is therefore **out of scope**, and the earlier three-tier
proposal was wrong. Telling a customer we do not serve sushi needs a different
signal — a general food lexicon, or an LLM classification — and should be
designed separately if it is wanted.

### The known false positive

"something sweet" measures 0.372, just inside the dish side. It will be treated
as a named dish. The consequence is mild — it searches for something sweet and
finds desserts, which is the right answer by a slightly wrong route — but it
should be recorded rather than discovered later.

---

## Design

### Component

One pure function, no I/O:

```
classify_dish_reference(distance: float | None) -> "named" | "absent" | "unknown"
```

- `named` — under `DISH_NAME_MAX_DISTANCE` (0.38). A specific dish is being asked for.
- `absent` — at or above it. No dish is named; this is a general request.
- `unknown` — distance is None (no embedding available). Behave exactly as today.

The threshold is one named constant carrying the measurement in its comment, so
the next person can see the 0.271 / 0.372 gap the number came from.

### Call site

In intent resolution, after retrieval has produced candidates and before the
extracted `dish` is trusted. On `absent`, clear `intent.dish` and `intent.items`
and let the turn proceed as the general recommendation it is.

`absent` is already handled correctly downstream — it means "no specific dish",
which routes to general recommendation. That is the answer "which item are
trending" should have produced all along. The bug was never that the system
mishandles "no dish"; it is that it never concludes there isn't one.

### Interaction with the stopword lists

The lists stay. They do useful work on the common cases at zero cost and with no
embedding dependency; this is the backstop for everything they miss. What
changes is that they stop being the only defence, so the next unanticipated word
is a non-event rather than a bug report.

---

## Rollout: log, then enforce

Enforcement ships **off**. The function logs its verdict against what the parser
decided, and the disagreement rate is measured on real traffic first.

This is not caution for its own sake. If the threshold is slightly wrong this
guardrail rejects *real* dish requests — a customer asking for pad thai told we
have no such thing — which is worse than the bug it fixes. The repo already uses
this pattern: the upsell grounding detector logs and does not act, precisely
because its measured precision (~62%) was not good enough to gate on.

The flag flips after the log shows the disagreements are the "today" class and
not the "pad thai" class.

---

## Error handling

| Failure | Behaviour |
|---|---|
| No embedding (Ollama down, timeout) | `unknown` — behave exactly as today |
| No candidates returned | `unknown`, not `absent` — an empty retrieval is not evidence about the question |
| Anything unexpected | log, return `unknown` |

A guardrail that can break a reply is worse than the bug it guards against. It
may only ever decline to act.

---

## Testing

`unittest`, matching the house style.

- `classify_dish_reference` returns `named` / `absent` / `unknown` at the
  boundary, above it, and for None
- the reported cases, asserted at the layer that produced them: "what is menu for
  today" and "which item are trending" resolve with no dish
- a real dish still resolves as named, including a misspelling
- an unavailable embedding leaves behaviour unchanged
- the threshold constant sits above the measured dish maximum and below the
  measured craving minimum — so a future edit to the number has to confront the
  data

The measurement itself is worth keeping as a script rather than a test: it is
model-specific and slow, and asserting exact distances would make it brittle.

---

## Dependencies and known gaps

**The thresholds are specific to `nomic-embed-text` and to this menu.** Switching
`embedding_provider` to Gemini requires re-measuring — the numbers are not
portable, and nothing in the code will complain if they silently stop being
right. This is the largest risk in the design.

**A 189-item menu is small.** A larger or more varied menu will shift the bands;
the gap may narrow. The measurement should be re-run when the catalogue grows
materially.

**"Food we don't serve" stays unsolved.** See the correction above.

**The filler words remain.** "there breakfast" and "want momo" still reach
retrieval as topics. This guardrail does not fix them — they are close enough to
real dishes to pass — and they are a separate, smaller cleanup.
