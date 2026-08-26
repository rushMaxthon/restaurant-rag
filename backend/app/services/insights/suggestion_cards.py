"""Structured, actionable cards for offer and combo suggestions in owner chat.

A chat answer is prose. Prose is the wrong surface for "create this offer" or
"activate this combo": the owner has to re-read a paragraph to find the name,
the discount and the price, and then leave the conversation to act on it.

These builders turn the rows a skill has *already* loaded into a small, stable
card payload the client renders beside the answer, with one action attached.
Three rules keep them safe:

* Read-only. Nothing here creates, approves or activates anything. A card names
  a target and the action that would apply; executing it is a separate,
  explicitly authenticated request the owner makes.
* Derived, never invented. Every figure on a card comes from a database row, so
  a card cannot state a discount the offer does not carry.
* Kept out of the narrator's input. Cards travel on `SkillResult.suggestions`,
  not on `data`, because `data` is fed to the model as `details` — a model shown
  its own cards starts describing them, which is exactly the prose the card
  exists to replace.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import (
    OwnerActionStatus,
    PersonalizedOfferDiscountType,
    PersonalizedOfferState,
)
from app.models.generated_combo import GeneratedCombo, GeneratedComboItem
from app.models.menu_item import MenuItem
from app.models.owner_action import OwnerActionProposal
from app.models.personalized_offer import PersonalizedOffer
from app.services.insights.scope import InsightsScope

# Cards are persisted with the turn, so an older card can be read back by a
# newer client. The version lets the client fall back rather than misread.
CARD_VERSION = 1

# Beyond this the cards stop being a summary and become a list to scroll.
MAX_CARDS = 3


def _number(value: Decimal | float | int | None) -> float | None:
    """Money as a plain float, so the client formats it the way it formats
    every other figure on the screen rather than parsing a preformatted string."""

    if value is None:
        return None
    return round(float(value), 2)


def _discount(
    discount_type: str | None, discount_value: Decimal | float | None
) -> dict[str, Any] | None:
    """What the customer gets, left unformatted.

    A flat discount is money, and money is rendered client-side so it matches
    every other figure on the screen. Sending a preformatted string here would
    put a second currency formatter in the codebase and let the two drift.
    """

    if discount_type is None or discount_type == PersonalizedOfferDiscountType.NONE.value:
        return None
    return {"type": discount_type, "value": _number(discount_value) or 0}


def _expired(proposal: OwnerActionProposal) -> bool:
    """Approval refuses an expired proposal, so a card must not offer one."""

    if proposal.expires_at is None:
        return False
    return proposal.expires_at <= datetime.now(UTC)


def _item_names(db: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Resolve menu item ids to names in one query.

    A card that says "on 3f2a…-…" instead of "on Paneer Tikka" is worse than no
    card, and resolving per proposal would be a query each.
    """

    if not item_ids:
        return {}
    rows = db.execute(
        select(MenuItem.id, MenuItem.name).where(MenuItem.id.in_(item_ids))
    ).all()
    return {row[0]: row[1] for row in rows}


def offer_cards_from_proposals(
    db: Session,
    proposals: list[OwnerActionProposal],
    *,
    limit: int = MAX_CARDS,
) -> list[dict[str, Any]]:
    """Cards for offers the manager has proposed but not yet created.

    The action is Create, and approving the proposal is what creates the offer —
    the same single path the Recommendations screen uses, so an offer can never
    be created here by a route that skips its discount ceilings.
    """

    # Only states approval actually accepts. A REJECTED or EXPIRED proposal is
    # still executable in the `is_executable` sense - it describes a real offer -
    # but approving one raises, so a card for it would show a Create button that
    # can only ever fail. EXECUTED is kept: it renders as already done.
    actionable = {
        OwnerActionStatus.PROPOSED,
        OwnerActionStatus.FAILED,
        OwnerActionStatus.EXECUTED,
    }
    considered = [
        row
        for row in proposals
        if row.is_executable and row.status in actionable and not _expired(row)
    ][:limit]
    if not considered:
        return []

    wanted: list[uuid.UUID] = []
    for proposal in considered:
        raw = proposal.action_payload or {}
        item_id = raw.get("applicable_item_id")
        if item_id:
            try:
                wanted.append(uuid.UUID(str(item_id)))
            except ValueError:
                continue
    names = _item_names(db, wanted)

    cards: list[dict[str, Any]] = []
    for proposal in considered:
        payload = proposal.action_payload or {}
        details: list[dict[str, str]] = []

        item_id = payload.get("applicable_item_id")
        applies_to = None
        if item_id:
            try:
                applies_to = names.get(uuid.UUID(str(item_id)))
            except ValueError:
                applies_to = None
        applies_to = (
            applies_to
            or payload.get("applicable_category")
            or payload.get("applicable_cuisine")
        )
        details.append({"label": "Applies to", "value": applies_to or "Whole menu"})

        discount = _discount(payload.get("discount_type"), payload.get("discount_value"))
        minimum = _number(payload.get("minimum_order_amount"))
        valid_days = payload.get("valid_for_days")

        # `executed_offer_id` is the proposal's own idempotency guard, so it is
        # also the honest signal for whether this has already been acted on.
        already = proposal.status == OwnerActionStatus.EXECUTED
        cards.append(
            {
                "version": CARD_VERSION,
                "kind": "offer",
                "id": str(proposal.id),
                "target_id": str(proposal.executed_offer_id) if already else None,
                "title": payload.get("name") or proposal.title,
                "summary": proposal.title if payload.get("name") else None,
                "status": proposal.status.value,
                "state": "active" if already else "creatable",
                "action": None if already else "create",
                "action_label": "Create offer",
                "details": details,
                "discount": discount,
                "minimum_order_amount": minimum,
                "valid_for_days": valid_days if isinstance(valid_days, int) else None,
                "pricing": None,
                "reason": proposal.rationale,
                "expected_impact": _number(proposal.expected_impact_amount),
                "expected_impact_basis": proposal.expected_impact_basis,
                "evidence": [],
            }
        )
    return cards


def combo_cards(
    db: Session,
    scope: InsightsScope,
    *,
    limit: int = MAX_CARDS,
) -> list[dict[str, Any]]:
    """Cards for combos the builder found in real baskets.

    Every combo here already exists as a row, so the action is Activate rather
    than Create: publishing one is a status change, not a creation.
    """

    # Imported lazily: the combo service pulls in a wide slice of the app, and
    # this module is imported from the skills registry at startup.
    from app.services.generated_combos import remaining_unique_users_to_publish

    conditions = [GeneratedCombo.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(
            GeneratedCombo.restaurant_location_id == scope.restaurant_location_id
        )

    rows = db.scalars(
        select(GeneratedCombo)
        .where(*conditions)
        # Draft first: a combo the owner can act on is worth more than one that
        # is already live, which is only a confirmation.
        .order_by(GeneratedCombo.is_active, GeneratedCombo.order_count.desc())
        # The item name is the whole point of a combo card, so it is loaded
        # with the combos rather than lazily, one query per item.
        .options(
            selectinload(GeneratedCombo.combo_items).selectinload(
                GeneratedComboItem.menu_item
            )
        )
        .limit(limit)
    ).all()

    cards: list[dict[str, Any]] = []
    for row in rows:
        items = [
            {
                "label": item.menu_item.name,
                "value": f"x{item.quantity}" if item.quantity > 1 else "",
            }
            for item in sorted(row.combo_items, key=lambda entry: entry.sort_order)
            if item.menu_item is not None
        ]

        live = row.status == "LIVE" or row.is_active
        evidence = [
            {"label": "Seen in", "value": f"{row.order_count} orders"},
            {"label": "Customers", "value": str(row.unique_user_count)},
        ]
        # A combo can be held back from customers even once live, and an owner
        # who activates one and sees nothing appear deserves to know why.
        remaining = remaining_unique_users_to_publish(row.unique_user_count)
        if not row.is_customer_visible and remaining > 0:
            evidence.append(
                {
                    "label": "To publish",
                    "value": f"{remaining} more customer{'s' if remaining != 1 else ''}",
                }
            )

        cards.append(
            {
                "version": CARD_VERSION,
                "kind": "combo",
                "id": str(row.id),
                "target_id": str(row.id),
                "title": row.combo_name,
                "summary": row.description,
                "status": row.status,
                "state": "active" if live else "activatable",
                "action": None if live else "activate",
                "action_label": "Activate combo",
                "details": items,
                "discount": None,
                "minimum_order_amount": None,
                "valid_for_days": None,
                "pricing": {
                    "original": _number(row.original_total_price),
                    "offered": _number(row.suggested_combo_price),
                    "saving": _number(
                        row.original_total_price - row.suggested_combo_price
                    ),
                },
                "reason": (
                    f"These items were bought together in {row.order_count} "
                    f"order{'s' if row.order_count != 1 else ''} by "
                    f"{row.unique_user_count} "
                    f"customer{'s' if row.unique_user_count != 1 else ''}."
                ),
                "expected_impact": None,
                "expected_impact_basis": None,
                "evidence": evidence,
            }
        )
    return cards


def offer_cards_from_catalogue(
    db: Session,
    scope: InsightsScope,
    *,
    limit: int = MAX_CARDS,
) -> list[dict[str, Any]]:
    """Cards for offers this restaurant already has but is not running.

    Distinct from the proposal cards above: these exist, so the action is
    Activate. An owner asking what offers they have is often one click from
    running one they set up and forgot.
    """

    conditions = [PersonalizedOffer.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(
            PersonalizedOffer.restaurant_location_id == scope.restaurant_location_id
        )

    rows = db.scalars(
        select(PersonalizedOffer)
        .where(
            *conditions,
            # EXPIRED and DISABLED are deliberate end states. Re-activating one
            # from a chat card would resurrect an offer someone retired, so only
            # the two reversible states are offered.
            PersonalizedOffer.state.in_(
                [PersonalizedOfferState.DRAFT, PersonalizedOfferState.PAUSED]
            ),
        )
        .order_by(PersonalizedOffer.created_at.desc())
        .limit(limit)
    ).all()
    if not rows:
        return []

    names = _item_names(
        db, [row.applicable_item_id for row in rows if row.applicable_item_id]
    )

    cards: list[dict[str, Any]] = []
    for row in rows:
        applies_to = (
            names.get(row.applicable_item_id)
            or row.applicable_category
            or row.applicable_cuisine
        )
        cards.append(
            {
                "version": CARD_VERSION,
                "kind": "offer",
                "id": str(row.id),
                "target_id": str(row.id),
                "title": row.name,
                "summary": None,
                "status": row.state.value,
                "state": "activatable",
                "action": "activate",
                "action_label": "Activate offer",
                "details": [
                    {"label": "Applies to", "value": applies_to or "Whole menu"}
                ],
                "discount": _discount(row.discount_type.value, row.discount_value),
                "minimum_order_amount": _number(row.minimum_order_amount),
                "valid_for_days": None,
                "pricing": None,
                "reason": (
                    "This offer is set up but not running, so it is currently "
                    "reaching nobody."
                ),
                "expected_impact": None,
                "expected_impact_basis": None,
                "evidence": [],
            }
        )
    return cards


__all__ = [
    "CARD_VERSION",
    "MAX_CARDS",
    "combo_cards",
    "offer_cards_from_catalogue",
    "offer_cards_from_proposals",
]
