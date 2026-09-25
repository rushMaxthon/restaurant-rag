# How one turn is routed

`run_turn` is ~2,200 lines, and almost all of it is nested helpers. The part
that decides **who gets to answer** is the top-level sequence after the reading,
and it is short. This is that sequence.

Written because a change went in without it. An optional-group offer was added
in the wrong place, never ran for `no` / `none` / `skip`, and left a customer's
half-built pizza unadded — worse than the behaviour it replaced. The map below
is generated from the source with `ast`; regenerate it after moving anything.

## The shape

Everything before `asked_before = _pending_choice()` is setup: the cart is
resolved, the currency bound, the plain reading taken, the held question read
and cleared. Everything after is a sequence of guards, **most of which return**.
The first one whose condition holds ends the turn.

```
asked_before = _pending_choice()          the choice we are waiting on
shown_before = ... if not asked_before    the dishes we last listed
wanted       = read_order_intent(...)     the model's reading of this message
```

`wanted` is not available until the reading is done, so any rule that needs to
know what the customer said has to sit **after** it — and any rule about the
pending choice has to sit **before the guard that re-asks it**.

## Two reads that happen before the reading

Both sit between `shown_before = ...` and `wanted = read_order_intent(...)`, and
both are deterministic: they read the message against what WE said last turn,
so the model is never asked what a bare number or a bare "how much" means
(measured, it answered "1" with nothing at all).

| line | returns | condition | what it is for |
|---|---|---|---|
| 3333 | **partly** | `removing is not None` — our own "which one shall I take off?" or "take all N off?" is standing | the reading is briefed with THAT question and the cart's lines as its options (never the last-shown list); a bare position takes that line off here and returns — it is never a yes to a destructive question |
| 3440 | **yes** | `plain == "price" and db and location` | "how much" / "kitne ka hai" about the dish being configured, the dish just offered, the list just shown, or the cart — `_answer_price_question`, from `prices_of` rows |
| 3457 | **partly** | `listed_now and plain is None` / `elif` a bare number with no list, no held question and no cart | "1", "the second one", "last": `ordinal_asked_for` against `listed_in_order(asked_before or shown_before)`. Sets `picked_by_number`; `wanted` is then built with `chose=[that name]` for a dish list, or `category`/`browse` for a section list (`picked_a_section`), and the reading is skipped. The `elif` returns: a position with nothing to count along is answered with the sections |

## The guards, in order

| line | returns | condition | what it is for |
|---|---|---|---|
| 3547 | **yes** | `removing is not None and chose` | the answer to "which one shall I take off?", as the reading read it against the cart's own lines (`lines_named_among`): one, several, or all — all is `_clear_whole_cart` |
| 3566 | | `asked_before["kind"] == "section" and chose` | they named a section off the numbered menu. The reading reports it as `chose` (the shape it is asked for whenever options are listed), and picking a section SHOWS it — so it becomes `category`, the same field typing "Pizza" produces |
| 3577 | **yes** | `clear_cart` | the reading says the whole cart should go, however it was worded: a question (`yes="clear_cart"`), or the clearing itself when that question is already standing; the empty-cart line when there is nothing to clear |
| 3619 | | `asked_before and asked_before.get("optional")` | the optional-group offer: whatever the message was, the dish is added, with the options it names (or `picked_by_number`) |
| 3641 | | `plain_before_holding == "checkout" and plain is None and not any(...)` | "that's all" with a list standing — the model made nothing of a message that plainly says "I am done" |
| 3659 | | `confirms is True and standing_offer and ...` | agreeing to a time we offered |
| 3669 | **yes** | `standing is not None and confirms is not None` | yes/no to a question `_hold` wrote down |
| 3677 | **yes** | `when and not cart and db` | a time, with nothing to order |
| 3697 | **yes** | `pay_now and db` | asking to pay |
| 3745 | **yes** | `cancel_order and not add and not browse and db` | cancelling, and only when the message is about nothing else; with no order waiting, a cart edit |
| 3745 | | `when and session_id` | a time, with a cart |
| 3749 | **yes** | `confirms is True and session_id` | agreeing to something |
| **3804** | **yes** | `asked_before and session_id and not any(chose, add, details, checkout, when, browse, category, wants_to_add, cancel_order, pay_now, asks_hours) and confirms is None` | **the re-ask.** A choice is standing and the message answered nothing, so the question is put again |
| 3830 | **yes** | `wants_to_add and not add and not chose and not browse ...` | a change of count — "make it 3" — read off the message |
| 3884 | **yes** | `plain == "cheapest" and db and location` | the cheapest dishes, from `price` |
| 3906 | **yes** | `plain == "suggest" and not asked_before` | "what do you recommend", from bestsellers and popularity |
| 4091 | | `chose and not asked_before and shown_before` | picking from a list we showed |
| 3949 | **yes** | `asks_hours and not when and db and location` | opening hours |
| 3978 | **yes** | `(browse or category) and (not add or names_the_section) and db and location` | showing a section or the menu |
| 3998 | **yes** | `wants_to_add and not add and not browse and not category and db and location` | "something else" with nothing named — suggest |
| | | `for one_dish in wanted["add"]` | the adds themselves |
| 4063 | **yes** | `details and session_id` | a name, an email, an address |
| 4063 | **yes** | `checkout and not cart and not actions` | checking out an empty cart |
| 4091 | **yes** | `records` | something happened — settle and say so |
| 4115 | **yes** | `not cart and db and session_id` | nothing happened and there is no cart |
| | **yes** | `for _round_index in range(rounds)` | the model's tool loop |

## The two rules this encodes

**A rule about the pending choice belongs above line 3804.** That guard is the
first thing to consult `asked_before`, and it returns. Below it, `asked_before`
is only ever read by branches that have already decided the message meant
something else.

**A rule that needs the reading belongs below line 3480.** `wanted` does not
exist before that.

So the window for "the customer is answering a choice" is **3480 → 3804**, and
it is the only window. That is where the optional-group offer has to go: after
the reading, before the re-ask.

**A rule that needs neither the reading nor the model belongs above 3480**,
where the price question and the pick-by-number sit: they only ever consult
what this conversation already wrote down, and skipping the reading is what
makes them answer in a fraction of a second rather than three.

## Why the re-ask guard is so specific

Its condition lists every key that means "this message did something", and
`confirms is None` on the end. The comment beside it records why:

> Saying no IS answering. Live: "that's all", after a list of three dishes, was
> answered "Sorry, I did not catch that. Just reply with one of these" — told
> off for declining.

That is the trap for an optional group, and it is worse than it looks. Measured
against the real reading, with the toppings question as `asked`:

| message | `confirms` | `chose` | `add` |
|---|---|---|---|
| `no` | `False` | – | – |
| `no thanks` | `False` | – | – |
| `none` | `None` | – | – |
| `skip` | `None` | – | – |
| `Mozzarella` | `None` | `['Mozzarella']` | – |
| `Mozzarella and mushroom` | `None` | – | `[('Mozzarella and mushroom', 1)]` |

Three different shapes for "no", and the same topping arrives as `chose` on one
run and as `add` on the next — **the reading is a model, and it is not
deterministic**. A rule that branches on which key was set will work in testing
and fail in front of a customer.

So anything that decides whether a built dish is kept must resolve the message
against the options **itself**, before these guards see it. The model's reading
is a hint here, not the answer.

## Regenerating

```python
import ast, pathlib
src = pathlib.Path("app/services/ordering_agent/loop.py").read_text(encoding="utf-8")
fn = next(n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == "run_turn")
started = False
for st in fn.body:
    if isinstance(st, ast.FunctionDef):
        continue
    if "asked_before = _pending_choice()" in (ast.get_source_segment(src, st) or ""):
        started = True
    if not started or not isinstance(st, ast.If):
        continue
    ends = any(isinstance(c, ast.Return) for c in ast.walk(st))
    test = " ".join((ast.get_source_segment(src, st.test) or "").split())
    print(f"{st.lineno:>6}  {'RETURNS' if ends else '':<8} {test[:100]}")
```
