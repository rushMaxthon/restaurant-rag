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

## The guards, in order

| line | returns | condition | what it is for |
|---|---|---|---|
| 2719 | | `plain_before_holding == "checkout" and plain is None and not any(...)` | "that's all" with a list standing — the model made nothing of a message that plainly says "I am done" |
| 2737 | | `confirms is True and standing_offer and ...` | agreeing to a time we offered |
| 2747 | **yes** | `standing is not None and confirms is not None` | yes/no to a question `_hold` wrote down |
| 2755 | **yes** | `when and not cart and db` | a time, with nothing to order |
| 2775 | **yes** | `pay_now and db` | asking to pay |
| 2784 | **yes** | `cancel_order and not add and not browse and db` | cancelling, and only when the message is about nothing else |
| 2794 | | `when and session_id` | a time, with a cart |
| 2798 | **yes** | `confirms is True and session_id` | agreeing to something |
| **2853** | **yes** | `asked_before and session_id and not any(chose, add, details, checkout, when, browse, category, wants_to_add, cancel_order, pay_now, asks_hours) and confirms is None` | **the re-ask.** A choice is standing and the message answered nothing, so the question is put again |
| 2873 | | `chose and not asked_before and shown_before` | picking from a list we showed |
| 2896 | **yes** | `asks_hours and not when and db and location` | opening hours |
| 2925 | **yes** | `(browse or category) and (not add or names_the_section) and db and location` | showing a section or the menu |
| 2945 | **yes** | `wants_to_add and not add and not browse and not category and db and location` | "something else" with nothing named — suggest |
| 2957 | | `for one_dish in wanted["add"]` | the adds themselves |
| 2968 | **yes** | `details and session_id` | a name, an email, an address |
| 3002 | **yes** | `checkout and not cart and not actions` | checking out an empty cart |
| 3030 | **yes** | `records` | something happened — settle and say so |
| 3054 | **yes** | `not cart and db and session_id` | nothing happened and there is no cart |
| 3065 | **yes** | `for _round_index in range(rounds)` | the model's tool loop |

## The two rules this encodes

**A rule about the pending choice belongs above line 2853.** That guard is the
first thing to consult `asked_before`, and it returns. Below it, `asked_before`
is only ever read by branches that have already decided the message meant
something else.

**A rule that needs the reading belongs below line 2664.** `wanted` does not
exist before that.

So the window for "the customer is answering a choice" is **2664 → 2853**, and
it is the only window. That is where the optional-group offer has to go: after
the reading, before the re-ask.

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
