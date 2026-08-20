"""Validation, approval, and execution of owner action proposals.

Approving a proposal can create a live offer and therefore cost real money, so
this module is deliberately conservative:

* The stored payload is what executes. It is never regenerated at approval time,
  so an owner always gets what they read.
* Discount ceilings are checked again here, not only when the proposal was
  written. A proposal can sit for days while configuration changes underneath it.
* `executed_offer_id` is the idempotency guard. Once a proposal has produced an
  offer it can never produce a second one, so a double-click cannot double-spend.
* Execution failures are recorded as FAILED rather than swallowed, because a
  proposal that silently did nothing is worse than one that reports the problem.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    OwnerActionStatus,
    PersonalizedOfferDiscountType,
)
from app.models.owner_action import OwnerActionProposal
from app.schemas.personalized_offer import PersonalizedOfferUpsertRequest
from app.services.insights.analyst.persistence import visible_origins
from app.services.insights.scope import InsightsScope

settings = get_settings()
logger = logging.getLogger(__name__)


class ActionValidationError(ValueError):
    """A proposal's payload is not safe or not valid to execute."""


@dataclass(slots=True)
class ExecutionResult:
    proposal: OwnerActionProposal
    offer_id: uuid.UUID | None
    already_executed: bool = False


def enforce_discount_caps(payload: PersonalizedOfferUpsertRequest) -> None:
    """Re-apply the platform's discount ceilings at execution time.

    These are the same limits the AI offer generator enforces. Checking them
    again here means a stale proposal cannot outlive a tightened policy.
    """

    if payload.discount_type == PersonalizedOfferDiscountType.PERCENTAGE:
        if payload.discount_value > settings.ai_max_percentage_discount:
            raise ActionValidationError(
                f"Percentage discount {payload.discount_value} exceeds the maximum "
                f"of {settings.ai_max_percentage_discount}"
            )
    elif payload.discount_type == PersonalizedOfferDiscountType.FLAT:
        if payload.discount_value > settings.ai_max_flat_discount:
            raise ActionValidationError(
                f"Flat discount {payload.discount_value} exceeds the maximum of "
                f"{settings.ai_max_flat_discount}"
            )

    if payload.discount_value < 0:
        raise ActionValidationError("Discount value cannot be negative")

    if payload.minimum_order_amount < settings.ai_min_order_threshold:
        raise ActionValidationError(
            f"Minimum order {payload.minimum_order_amount} is below the threshold "
            f"of {settings.ai_min_order_threshold}"
        )


def validate_payload(raw_payload: dict) -> PersonalizedOfferUpsertRequest:
    """Parse a stored payload into an offer request and apply the caps."""

    try:
        payload = PersonalizedOfferUpsertRequest.model_validate(raw_payload)
    except ValidationError as error:
        raise ActionValidationError(f"Proposal payload is not a valid offer: {error}") from error

    enforce_discount_caps(payload)
    return payload


def list_proposals(
    db: Session,
    *,
    scope: InsightsScope,
    statuses: list[OwnerActionStatus] | None = None,
    limit: int = 50,
) -> list[OwnerActionProposal]:
    query = select(OwnerActionProposal).where(
        OwnerActionProposal.restaurant_id == scope.restaurant_id,
        # Analyst output is filtered out at the read path, not only at the write
        # path. Two independent gates means a row written by a future phase — or
        # by a run started before the flag was turned off — still cannot surface.
        OwnerActionProposal.origin.in_(visible_origins()),
    )
    if scope.restaurant_location_id is not None:
        query = query.where(
            OwnerActionProposal.restaurant_location_id == scope.restaurant_location_id
        )
    if statuses:
        query = query.where(OwnerActionProposal.status.in_(statuses))
    return list(
        db.scalars(
            query.order_by(
                OwnerActionProposal.generated_at.desc(),
                OwnerActionProposal.priority.desc(),
            ).limit(limit)
        ).all()
    )


def get_proposal_for_scope(
    db: Session,
    *,
    scope: InsightsScope,
    proposal_id: uuid.UUID,
) -> OwnerActionProposal | None:
    """Load one proposal, scoped so another restaurant's id resolves to nothing."""

    return db.scalars(
        select(OwnerActionProposal).where(
            OwnerActionProposal.id == proposal_id,
            OwnerActionProposal.restaurant_id == scope.restaurant_id,
        )
    ).first()


def is_expired(proposal: OwnerActionProposal, *, now: datetime | None = None) -> bool:
    if proposal.expires_at is None:
        return False
    return proposal.expires_at <= (now or datetime.now(UTC))


def reject_proposal(
    db: Session,
    *,
    proposal: OwnerActionProposal,
    decided_by_user_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> OwnerActionProposal:
    if proposal.status not in {OwnerActionStatus.PROPOSED, OwnerActionStatus.FAILED}:
        raise ActionValidationError(
            f"A proposal in state {proposal.status.value} cannot be rejected"
        )

    proposal.status = OwnerActionStatus.REJECTED
    proposal.decided_at = now or datetime.now(UTC)
    proposal.decided_by_user_id = decided_by_user_id
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return proposal


def approve_proposal(
    db: Session,
    *,
    proposal: OwnerActionProposal,
    decided_by_user_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> ExecutionResult:
    """Approve a proposal and, if it is executable, create the offer.

    Imported lazily because the offer service pulls in a large slice of the
    application, and this module is reached from the Celery task path.
    """

    from app.services.personalized_offers import create_restaurant_offer

    resolved_now = now or datetime.now(UTC)

    # Idempotency: a proposal that already produced an offer returns that offer
    # rather than creating a second one.
    if proposal.status == OwnerActionStatus.EXECUTED:
        return ExecutionResult(
            proposal=proposal,
            offer_id=proposal.executed_offer_id,
            already_executed=True,
        )

    if proposal.status in {OwnerActionStatus.REJECTED, OwnerActionStatus.EXPIRED}:
        raise ActionValidationError(
            f"A proposal in state {proposal.status.value} cannot be approved"
        )

    if is_expired(proposal, now=resolved_now):
        proposal.status = OwnerActionStatus.EXPIRED
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        raise ActionValidationError("This proposal has expired and was not executed")

    proposal.decided_at = resolved_now
    proposal.decided_by_user_id = decided_by_user_id

    if not proposal.is_executable:
        # Advisory recommendations are acknowledged, not run.
        proposal.status = OwnerActionStatus.APPROVED
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        return ExecutionResult(proposal=proposal, offer_id=None)

    try:
        payload = validate_payload(proposal.action_payload)
    except ActionValidationError as error:
        proposal.status = OwnerActionStatus.FAILED
        proposal.failure_reason = str(error)
        db.add(proposal)
        db.commit()
        db.refresh(proposal)
        raise

    try:
        offer = create_restaurant_offer(
            db,
            restaurant_id=proposal.restaurant_id,
            payload=payload,
        )
    except Exception as error:  # noqa: BLE001 - any failure must be recorded, not lost
        db.rollback()
        # Re-read the row: the rollback discarded the in-flight decision fields.
        refreshed = db.get(OwnerActionProposal, proposal.id)
        if refreshed is not None:
            refreshed.status = OwnerActionStatus.FAILED
            refreshed.failure_reason = str(error)
            refreshed.decided_at = resolved_now
            refreshed.decided_by_user_id = decided_by_user_id
            db.add(refreshed)
            db.commit()
            db.refresh(refreshed)
            proposal = refreshed
        logger.exception(
            "Action proposal execution failed proposal_id=%s restaurant_id=%s",
            proposal.id,
            proposal.restaurant_id,
        )
        raise ActionValidationError(f"Unable to create the offer: {error}") from error

    proposal.status = OwnerActionStatus.EXECUTED
    proposal.executed_at = resolved_now
    proposal.executed_offer_id = offer.id
    proposal.failure_reason = None
    db.add(proposal)
    db.commit()
    db.refresh(proposal)

    logger.info(
        "Action proposal executed proposal_id=%s restaurant_id=%s offer_id=%s type=%s",
        proposal.id,
        proposal.restaurant_id,
        offer.id,
        proposal.action_type.value,
    )
    return ExecutionResult(proposal=proposal, offer_id=offer.id)


def expire_stale_proposals(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    now: datetime | None = None,
) -> int:
    """Mark undecided proposals past their expiry, so the list stays current."""

    resolved_now = now or datetime.now(UTC)
    rows = db.scalars(
        select(OwnerActionProposal).where(
            OwnerActionProposal.restaurant_id == restaurant_id,
            OwnerActionProposal.status == OwnerActionStatus.PROPOSED,
            OwnerActionProposal.expires_at.is_not(None),
            OwnerActionProposal.expires_at <= resolved_now,
        )
    ).all()

    for row in rows:
        row.status = OwnerActionStatus.EXPIRED
        db.add(row)
    return len(rows)


def default_expiry(now: datetime) -> datetime:
    return now + timedelta(days=settings.action_proposal_expiry_days)


__all__ = [
    "ActionValidationError",
    "ExecutionResult",
    "approve_proposal",
    "default_expiry",
    "enforce_discount_caps",
    "expire_stale_proposals",
    "get_proposal_for_scope",
    "is_expired",
    "list_proposals",
    "reject_proposal",
    "validate_payload",
]
