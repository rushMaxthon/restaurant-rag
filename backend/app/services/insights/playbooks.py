"""Turns Phase 2 findings into concrete, executable recommendations.

Deterministic: every proposal, its wording, and its expected impact come from
arithmetic over the facts an insight already carried. No LLM is involved.

Two honesty rules shape what is here:

* A proposal is only marked executable when approving it produces something the
  platform can genuinely do. Where the data supports an observation but not an
  automated fix — a cancellation spike, whose cause is not recorded anywhere —
  the recommendation is advisory and creates nothing.
* Expected impact is a recovery *assumption* applied to money actually lost, not
  a forecast. The assumption travels with the number so it can never be read as
  a promise.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Iterable, Sequence

from app.config import get_settings
from app.models.enums import (
    OwnerActionType,
    OwnerInsightType,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferState,
    PersonalizedOfferType,
)
from app.services.insights.metrics import DAYPARTS
from app.services.insights.rules import CandidateInsight, money, percent, plain_percent

settings = get_settings()

TWO_PLACES = Decimal("0.01")

# Resolves a dish name to a menu item id within the restaurant being analysed.
# Item metrics are grouped by dish name so branch duplicates collapse, which
# means an id has to be looked up again when an offer needs one.
MenuItemResolver = Callable[[str], uuid.UUID | None]


@dataclass(slots=True)
class ComboOpportunity:
    """A basket pair already observed in real orders."""

    combo_id: uuid.UUID
    combo_name: str
    order_count: int
    unique_user_count: int
    confidence_score: Decimal
    original_total_price: Decimal
    suggested_combo_price: Decimal


@dataclass(slots=True)
class ActionProposal:
    action_type: OwnerActionType
    dedupe_key: str
    title: str
    rationale: str
    priority: Decimal
    is_executable: bool
    action_payload: dict[str, Any] = field(default_factory=dict)
    source_facts: dict[str, Any] = field(default_factory=dict)
    expected_impact_amount: Decimal | None = None
    expected_impact_basis: str | None = None
    # Links the proposal back to the finding that justified it, so generation
    # can attach the persisted insight row.
    insight_dedupe_key: str | None = None


def _quantize(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _recovery_estimate(lost_amount: float) -> tuple[Decimal, str]:
    """Money a promotion might win back, plus the assumption behind it."""

    rate = settings.action_recovery_rate
    estimate = _quantize(abs(lost_amount) * rate)
    basis = (
        f"Estimate only: {int(rate * 100)}% of the {money(abs(lost_amount))} lost "
        "in this period, assuming the promotion recovers part of the decline."
    )
    return estimate, basis


def _daypart_hours(daypart: str) -> tuple[int, int] | None:
    windows = [(start, end) for name, start, end in DAYPARTS if name == daypart]
    if not windows:
        return None
    return min(start for start, _ in windows), max(end for _, end in windows)


def _base_offer_payload(
    *,
    name: str,
    offer_type: PersonalizedOfferType,
    audience_type: PersonalizedOfferAudience,
    discount_percent: Decimal,
    cta_label: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "name": name[:255],
        "offer_type": offer_type.value,
        "audience_type": audience_type.value,
        # Approving is an explicit decision to run the promotion, so it goes
        # live rather than landing in drafts where nothing would happen.
        "state": PersonalizedOfferState.ACTIVE.value,
        "discount_type": PersonalizedOfferDiscountType.PERCENTAGE.value,
        "discount_value": str(_quantize(discount_percent)),
        "minimum_order_amount": str(_quantize(settings.action_default_minimum_order)),
        "valid_for_days": settings.action_default_valid_for_days,
        "cta_label": cta_label[:80],
        "notes": notes[:2000],
        "business_rules": {},
    }


# --- individual playbooks --------------------------------------------------


def _promote_item(
    insight: CandidateInsight, *, resolve_menu_item: MenuItemResolver | None
) -> ActionProposal | None:
    subject = insight.subject
    if subject is None:
        return None

    menu_item_id = resolve_menu_item(subject) if resolve_menu_item is not None else None
    if menu_item_id is None:
        # Without a real menu item there is nothing to attach an offer to, and
        # guessing one would discount the wrong dish.
        return None

    lost = float(insight.facts.get("absolute_change") or 0.0)
    estimate, basis = _recovery_estimate(lost)
    discount = settings.action_default_discount_percent

    payload = _base_offer_payload(
        name=f"{subject} boost",
        offer_type=PersonalizedOfferType.FAVORITE_ITEM,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        discount_percent=discount,
        cta_label="Order now",
        notes=f"Proposed by the AI Restaurant Manager after {subject} sales fell.",
    )
    payload["applicable_item_id"] = str(menu_item_id)

    return ActionProposal(
        action_type=OwnerActionType.PROMOTE_ITEM,
        dedupe_key=f"PROMOTE_ITEM:{insight.dedupe_key}",
        title=f"Promote {subject} at {plain_percent(float(discount))} off",
        rationale=(
            f"{subject} fell by {money(lost)} this period. A short discount puts it "
            "back in front of customers who have stopped ordering it."
        ),
        priority=Decimal(str(abs(lost))),
        is_executable=True,
        action_payload=payload,
        source_facts=dict(insight.facts),
        expected_impact_amount=estimate,
        expected_impact_basis=basis,
        insight_dedupe_key=insight.dedupe_key,
    )


def _promote_category(insight: CandidateInsight) -> ActionProposal | None:
    subject = insight.subject
    if subject is None:
        return None

    lost = float(insight.facts.get("absolute_change") or 0.0)
    estimate, basis = _recovery_estimate(lost)
    discount = settings.action_default_discount_percent

    payload = _base_offer_payload(
        name=f"{subject} category offer",
        offer_type=PersonalizedOfferType.PREFERENCE_MATCH,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        discount_percent=discount,
        cta_label="See offers",
        notes=f"Proposed by the AI Restaurant Manager after the {subject} category declined.",
    )
    payload["applicable_category"] = subject[:120]

    return ActionProposal(
        action_type=OwnerActionType.PROMOTE_CATEGORY,
        dedupe_key=f"PROMOTE_CATEGORY:{insight.dedupe_key}",
        title=f"Run a {subject} offer",
        rationale=(
            f"The {subject} category fell by {money(lost)} this period. A "
            "category-wide discount lifts every dish in it at once."
        ),
        priority=Decimal(str(abs(lost))),
        is_executable=True,
        action_payload=payload,
        source_facts=dict(insight.facts),
        expected_impact_amount=estimate,
        expected_impact_basis=basis,
        insight_dedupe_key=insight.dedupe_key,
    )


def _daypart_offer(insight: CandidateInsight) -> ActionProposal | None:
    subject = insight.subject
    if subject is None:
        return None

    lost = float(insight.facts.get("absolute_change") or 0.0)
    estimate, basis = _recovery_estimate(lost)
    discount = settings.action_default_discount_percent
    hours = _daypart_hours(subject)

    # The offer engine has no hour-of-day restriction, so this discount will
    # apply at every hour. Saying so in the title and rationale matters: an
    # owner who believes they are running a dinner-only special would otherwise
    # discount lunch too.
    payload = _base_offer_payload(
        name=f"{subject} recovery offer",
        offer_type=PersonalizedOfferType.CUSTOM,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        discount_percent=discount,
        cta_label="Order now",
        notes=(
            f"Proposed by the AI Restaurant Manager after {subject} trade weakened. "
            "Applies at all hours: hour-of-day restriction is not supported yet."
        ),
    )
    payload["business_rules"] = {
        "insight_daypart": subject,
        "daypart_hours": list(hours) if hours else None,
        "time_restriction_enforced": False,
    }

    return ActionProposal(
        action_type=OwnerActionType.DAYPART_OFFER,
        dedupe_key=f"DAYPART_OFFER:{insight.dedupe_key}",
        title=f"All-day offer to rebuild {subject.lower()} trade",
        rationale=(
            f"{subject} revenue fell by {money(lost)} this period. Note that the "
            "discount runs at all hours, because time-of-day restriction is not "
            "supported yet."
        ),
        priority=Decimal(str(abs(lost))),
        is_executable=True,
        action_payload=payload,
        source_facts=dict(insight.facts),
        expected_impact_amount=estimate,
        expected_impact_basis=basis,
        insight_dedupe_key=insight.dedupe_key,
    )


def _winback_inactive(insight: CandidateInsight) -> ActionProposal:
    lost = float(insight.facts.get("absolute_change") or 0.0)
    estimate, basis = _recovery_estimate(lost)
    discount = settings.action_winback_discount_percent

    payload = _base_offer_payload(
        name="Win back lapsed regulars",
        offer_type=PersonalizedOfferType.ORDER_HISTORY_MATCH,
        audience_type=PersonalizedOfferAudience.INACTIVE_USERS,
        discount_percent=discount,
        cta_label="Come back",
        notes="Proposed by the AI Restaurant Manager after returning-customer spend fell.",
    )

    return ActionProposal(
        action_type=OwnerActionType.WINBACK_INACTIVE,
        dedupe_key=f"WINBACK_INACTIVE:{insight.dedupe_key}",
        title=f"Win back lapsed regulars with {plain_percent(float(discount))} off",
        rationale=(
            f"Returning customers spent {money(lost)} less this period. This offer "
            "targets customers who have not ordered recently."
        ),
        priority=Decimal(str(abs(lost))),
        is_executable=True,
        action_payload=payload,
        source_facts=dict(insight.facts),
        expected_impact_amount=estimate,
        expected_impact_basis=basis,
        insight_dedupe_key=insight.dedupe_key,
    )


def _welcome_new_customers(insight: CandidateInsight) -> ActionProposal:
    lost = float(insight.facts.get("absolute_change") or 0.0)
    estimate, basis = _recovery_estimate(lost)
    discount = settings.action_welcome_discount_percent

    payload = _base_offer_payload(
        name="First order welcome offer",
        offer_type=PersonalizedOfferType.WELCOME_FIRST_ORDER,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        discount_percent=discount,
        cta_label="Try us",
        notes="Proposed by the AI Restaurant Manager after new-customer spend fell.",
    )

    return ActionProposal(
        action_type=OwnerActionType.WELCOME_NEW_CUSTOMERS,
        dedupe_key=f"WELCOME_NEW_CUSTOMERS:{insight.dedupe_key}",
        title=f"Offer first-time customers {plain_percent(float(discount))} off",
        rationale=(
            f"New-customer spend fell by {money(lost)} this period. A first-order "
            "discount lowers the barrier for people trying you for the first time."
        ),
        priority=Decimal(str(abs(lost))),
        is_executable=True,
        action_payload=payload,
        source_facts=dict(insight.facts),
        expected_impact_amount=estimate,
        expected_impact_basis=basis,
        insight_dedupe_key=insight.dedupe_key,
    )


def _operational_review(insight: CandidateInsight) -> ActionProposal:
    cancelled = int(insight.facts.get("cancelled_orders") or 0)
    rate = float(insight.facts.get("cancellation_rate") or 0.0)
    value = float(insight.facts.get("cancelled_value") or 0.0)

    return ActionProposal(
        action_type=OwnerActionType.OPERATIONAL_REVIEW,
        dedupe_key=f"OPERATIONAL_REVIEW:{insight.dedupe_key}",
        title="Review why orders are being cancelled",
        rationale=(
            f"{cancelled} orders were cancelled this period ({percent(rate)}), worth "
            f"{money(value)}. Cancellation reasons are not recorded, so this needs a "
            "look at the orders themselves rather than an automated fix."
        ),
        priority=Decimal(str(abs(value))),
        # Nothing to execute: the cause is not in the data, and inventing a
        # discount for it would be guesswork.
        is_executable=False,
        source_facts=dict(insight.facts),
        insight_dedupe_key=insight.dedupe_key,
    )


def _protect_supply(insight: CandidateInsight) -> ActionProposal:
    subject = insight.subject or "Your best seller"
    gained = float(insight.facts.get("absolute_change") or 0.0)

    return ActionProposal(
        action_type=OwnerActionType.PROTECT_SUPPLY,
        dedupe_key=f"PROTECT_SUPPLY:{insight.dedupe_key}",
        title=f"Keep {subject} in stock",
        rationale=(
            f"{subject} grew by {money(gained)} this period. Running out of it would "
            "cost more than any promotion would gain."
        ),
        priority=Decimal(str(abs(gained))),
        is_executable=False,
        source_facts=dict(insight.facts),
        insight_dedupe_key=insight.dedupe_key,
    )


def _cross_sell(combo: ComboOpportunity) -> ActionProposal | None:
    if combo.confidence_score < settings.action_combo_min_confidence:
        return None

    saving = _quantize(combo.original_total_price - combo.suggested_combo_price)
    if saving <= 0:
        return None

    discount_percent = _quantize(
        (saving / combo.original_total_price) * 100
        if combo.original_total_price > 0
        else Decimal("0")
    )
    if discount_percent <= 0:
        return None

    payload = _base_offer_payload(
        name=f"{combo.combo_name} combo",
        offer_type=PersonalizedOfferType.COMBO_AFFINITY,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        discount_percent=discount_percent,
        cta_label="Add combo",
        notes=(
            "Proposed by the AI Restaurant Manager from a basket pair seen in real "
            f"orders ({combo.order_count} orders, {combo.unique_user_count} customers)."
        ),
    )

    return ActionProposal(
        action_type=OwnerActionType.CROSS_SELL_COMBO,
        dedupe_key=f"CROSS_SELL_COMBO:{combo.combo_id}",
        title=f"Bundle {combo.combo_name}",
        rationale=(
            f"{combo.order_count} orders already included these items together. "
            f"Bundling them at {money(float(combo.suggested_combo_price))} instead of "
            f"{money(float(combo.original_total_price))} makes the pairing explicit."
        ),
        priority=Decimal(str(combo.order_count)),
        is_executable=True,
        action_payload=payload,
        source_facts={
            "combo_id": str(combo.combo_id),
            "order_count": combo.order_count,
            "unique_user_count": combo.unique_user_count,
            "confidence_score": float(combo.confidence_score),
            "original_total_price": float(combo.original_total_price),
            "suggested_combo_price": float(combo.suggested_combo_price),
        },
        # No baseline loss to recover from, so no impact figure is offered
        # rather than an invented one.
        expected_impact_amount=None,
        expected_impact_basis=(
            "No estimate: this is a new opportunity with no prior decline to recover."
        ),
    )


PLAYBOOKS: dict[OwnerInsightType, Callable[[CandidateInsight], ActionProposal | None]] = {
    OwnerInsightType.CATEGORY_DECLINE: _promote_category,
    OwnerInsightType.DAYPART_WEAKNESS: _daypart_offer,
    OwnerInsightType.RETURNING_CUSTOMER_DECLINE: _winback_inactive,
    OwnerInsightType.NEW_CUSTOMER_DECLINE: _welcome_new_customers,
    OwnerInsightType.CANCELLATION_SPIKE: _operational_review,
    OwnerInsightType.ITEM_SURGE: _protect_supply,
}


def build_proposals(
    insights: Iterable[CandidateInsight],
    *,
    resolve_menu_item: MenuItemResolver | None = None,
    combos: Sequence[ComboOpportunity] = (),
    limit: int | None = None,
) -> list[ActionProposal]:
    """Map findings onto recommended actions, highest value first."""

    proposals: list[ActionProposal] = []

    for insight in insights:
        if insight.insight_type == OwnerInsightType.ITEM_DECLINE:
            proposal = _promote_item(insight, resolve_menu_item=resolve_menu_item)
        else:
            playbook = PLAYBOOKS.get(insight.insight_type)
            proposal = playbook(insight) if playbook is not None else None

        if proposal is not None:
            proposals.append(proposal)

    for combo in combos:
        proposal = _cross_sell(combo)
        if proposal is not None:
            proposals.append(proposal)

    seen: set[str] = set()
    deduped: list[ActionProposal] = []
    for proposal in proposals:
        if proposal.dedupe_key in seen:
            continue
        seen.add(proposal.dedupe_key)
        deduped.append(proposal)

    # Executable proposals first: an owner can act on those today, while an
    # advisory only tells them where to look.
    deduped.sort(
        key=lambda row: (not row.is_executable, -float(row.priority), row.title.lower())
    )

    resolved_limit = limit if limit is not None else settings.action_max_open_proposals
    return deduped[:resolved_limit]


__all__ = [
    "ActionProposal",
    "ComboOpportunity",
    "MenuItemResolver",
    "PLAYBOOKS",
    "build_proposals",
]
