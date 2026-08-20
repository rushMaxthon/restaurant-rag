from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.enums import (
    InsightNarrationSource,
    OwnerActionStatus,
    OwnerInsightStatus,
)
from app.models.user import User
from app.schemas.insights import (
    ActionOutcomeResponse,
    DiagnosticsSnapshotResponse,
    InsightsPeriod,
    InsightsScopeResponse,
    OfferPerformanceResponse,
    OfferPerformanceRow,
    OwnerBriefingResponse,
    OwnerInsightResponse,
    OwnerInsightStatusUpdate,
)
from app.schemas.owner_chat import (
    OwnerChatClearResponse,
    OwnerChatHistoryItem,
    OwnerChatRequest,
    OwnerChatResponse,
)
from app.schemas.owner_actions import (
    OwnerActionApprovalResponse,
    OwnerActionProposalResponse,
)
from app.services.auth import get_current_user
from app.services.insights.actions import (
    ActionValidationError,
    approve_proposal,
    get_proposal_for_scope,
    list_proposals,
    reject_proposal,
)
from app.services.insights.chat import (
    answer_question,
    clear_chat_history,
    get_chat_history,
    stream_answer,
)
from app.services.insights.offer_performance import fetch_offer_performance
from app.services.insights.outcomes import get_outcomes_by_proposal, list_outcomes
from app.services.insights.periods import local_today, resolve_period_comparison
from app.services.insights.generation import (
    build_live_briefing,
    live_findings_for,
    get_insight_for_scope,
    get_latest_briefing,
    list_insights,
    set_insight_status,
)
from app.services.insights.scope import resolve_insights_scope
from app.services.insights.service import get_diagnostics_snapshot

router = APIRouter(prefix="/owner/insights", tags=["Owner Insights"])


@router.get("/diagnostics", response_model=DiagnosticsSnapshotResponse)
def get_diagnostics(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    window_days: int | None = Query(default=None, ge=1),
    restaurant_id: uuid.UUID | None = Query(default=None),
    restaurant_location_id: uuid.UUID | None = Query(default=None),
    refresh: bool = Query(default=False),
) -> DiagnosticsSnapshotResponse:
    """Period-over-period diagnostics for one restaurant.

    `restaurant_id` is accepted but never trusted for owners: the scope resolver
    pins an owner to their own restaurant and rejects any other value.
    """

    scope = resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )
    return get_diagnostics_snapshot(
        db,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
        window_days=window_days,
        use_cache=not refresh,
    )


@router.get("/briefing", response_model=OwnerBriefingResponse)
def get_briefing(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    window_days: int | None = Query(default=None, ge=1),
    restaurant_id: uuid.UUID | None = Query(default=None),
    restaurant_location_id: uuid.UUID | None = Query(default=None),
) -> OwnerBriefingResponse:
    """The briefing for a period, computed live, or the stored nightly one.

    Naming a period returns a briefing for exactly that period, worked out on
    the spot from the same rules the nightly run uses and stored nowhere. Before
    this, the stored briefing was shown beside figures for whatever period the
    owner had selected — one card describing two different windows, with the
    stored headline winning because it is the largest text on the screen.

    With no period named the stored briefing is returned as before, now marked
    stale when it no longer reaches the last complete day.
    """

    scope = resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )

    if date_from is not None or date_to is not None or window_days is not None:
        comparison = resolve_period_comparison(
            date_from=date_from, date_to=date_to, window_days=window_days
        )
        headline, narrative, candidates = build_live_briefing(
            db, scope=scope, comparison=comparison
        )
        return OwnerBriefingResponse(
            # Not a stored row, so it carries no identity of its own. A nil id
            # is honest about that: there is nothing to fetch again later.
            id=uuid.UUID(int=0),
            restaurant_id=scope.restaurant_id,
            restaurant_location_id=scope.restaurant_location_id,
            period_start=comparison.current.start_date,
            period_end=comparison.current.end_date,
            previous_period_start=comparison.previous.start_date,
            previous_period_end=comparison.previous.end_date,
            headline=headline,
            narrative=narrative,
            narration_source=InsightNarrationSource.TEMPLATE,
            insight_count=len(candidates),
            generated_at=datetime.now(UTC),
            insights=[],
            is_live=True,
        )

    briefing = get_latest_briefing(db, scope=scope)
    if briefing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No briefing has been generated yet",
        )

    response = OwnerBriefingResponse.model_validate(briefing)
    response.insights = [
        OwnerInsightResponse.model_validate(insight)
        for insight in list_insights(db, scope=scope, limit=50)
        if insight.briefing_id == briefing.id
    ]

    # Stale means "does not describe the business as it stands now". The card is
    # the loudest thing on the screen and had no way to say that its headline
    # was two days and a whole trend out of date.
    # Measured against today, because windows now include today. A briefing
    # that stops at yesterday is a day behind the figures beside it.
    days_behind = (local_today() - briefing.period_end).days
    if days_behind > 0:
        response.is_stale = True
        response.stale_reason = (
            f"This briefing covers up to {briefing.period_end:%d %b}, "
            f"so it is {days_behind} day{'s' if days_behind != 1 else ''} behind."
        )
    return response


# Namespace for the deterministic ids given to findings that have no row yet,
# so the same finding keeps the same id between requests.
LIVE_INSIGHT_NAMESPACE = uuid.UUID("6f1d4d16-0f37-4a3f-9a3a-4b1a2f9c7d10")


@router.get("/feed", response_model=list[OwnerInsightResponse])
def get_insight_feed(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    window_days: int | None = Query(default=None, ge=1),
    restaurant_id: uuid.UUID | None = Query(default=None),
    restaurant_location_id: uuid.UUID | None = Query(default=None),
    insight_status: list[OwnerInsightStatus] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OwnerInsightResponse]:
    """Ranked insight cards for a period, newest first.

    Naming a period makes this and the briefing read from **one** analysis of
    that period. Stored rows win wherever they exist, because they carry the
    owner's own seen/dismissed decisions; anything the analysis found that has
    no row yet is returned alongside them, marked live.

    Without a period this returns the stored feed exactly as before.
    """

    scope = resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )
    rows = list_insights(db, scope=scope, statuses=insight_status, limit=limit)
    stored = [OwnerInsightResponse.model_validate(row) for row in rows]

    if date_from is None and date_to is None and window_days is None:
        return stored

    comparison = resolve_period_comparison(
        date_from=date_from, date_to=date_to, window_days=window_days
    )
    period = comparison.current

    # Only findings that belong to the window on screen. A stored row from
    # another run's window is a different period's finding.
    in_window = [
        row
        for row in stored
        if row.period_start <= period.end_date and row.period_end >= period.start_date
    ]
    # Dismissed findings stay dismissed: recomputing must not resurrect
    # something the owner has already waved away.
    decided = {
        (row.dimension, row.subject, row.insight_type) for row in stored
    }

    live: list[OwnerInsightResponse] = []
    for candidate in live_findings_for(db, scope=scope, comparison=comparison):
        key = (candidate.dimension, candidate.subject, candidate.insight_type)
        if key in decided:
            continue
        live.append(
            OwnerInsightResponse(
                id=uuid.uuid5(
                    LIVE_INSIGHT_NAMESPACE,
                    f"{scope.restaurant_id}:{candidate.dedupe_key}:{period.start_date}",
                ),
                insight_type=candidate.insight_type,
                severity=candidate.severity,
                status=OwnerInsightStatus.NEW,
                title=candidate.title,
                body=candidate.body,
                dimension=candidate.dimension,
                subject=candidate.subject,
                score=float(candidate.score),
                root_cause=candidate.root_cause,
                period_start=period.start_date,
                period_end=period.end_date,
                facts=candidate.facts,
                created_at=datetime.now(UTC),
                acknowledged_at=None,
                is_live=True,
            )
        )

    merged = in_window + live
    merged.sort(key=lambda row: row.score, reverse=True)
    return merged[:limit]


@router.patch("/feed/{insight_id}", response_model=OwnerInsightResponse)
def update_insight_status(
    insight_id: uuid.UUID,
    payload: OwnerInsightStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> OwnerInsightResponse:
    """Mark an insight seen or dismissed.

    Dismissal also suppresses the same finding for the cooldown window, so the
    feed does not argue with an owner who has already decided.
    """

    scope = resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=restaurant_id,
    )
    insight = get_insight_for_scope(db, scope=scope, insight_id=insight_id)
    if insight is None:
        # Scoped lookup, so another restaurant's insight is indistinguishable
        # from one that does not exist.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Insight not found",
        )

    updated = set_insight_status(db, insight=insight, status=payload.status)
    return OwnerInsightResponse.model_validate(updated)


@router.post("/chat/message", response_model=OwnerChatResponse)
def send_owner_chat_message(
    payload: OwnerChatRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> OwnerChatResponse:
    """Ask a question about this restaurant's business.

    The scope is resolved from the authenticated user before the question is
    read, so nothing in the message text can widen it.
    """

    scope = resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=payload.restaurant_id,
        restaurant_location_id=payload.restaurant_location_id,
    )
    turn = answer_question(
        db,
        scope=scope,
        user_id=current_user.id,
        question=payload.message,
        session_id=payload.session_id,
    )
    return OwnerChatResponse(
        session_id=turn.session_id,
        answer=turn.answer,
        skill=turn.skill,
        answer_source=turn.answer_source,
        routed_by=turn.routed_by,
        fallback_reason=turn.fallback_reason,
        facts=turn.facts or {},
    )


@router.post("/chat/message/stream")
def stream_owner_chat_message(
    payload: OwnerChatRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    """The same answer as `/chat/message`, streamed as server-sent events.

    Frame names match the customer assistant (`meta`, `token`, `done`) so a
    client can reuse one parser.
    """

    scope = resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=payload.restaurant_id,
        restaurant_location_id=payload.restaurant_location_id,
    )
    return StreamingResponse(
        stream_answer(
            db,
            scope=scope,
            user_id=current_user.id,
            question=payload.message,
            session_id=payload.session_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/history", response_model=list[OwnerChatHistoryItem])
def list_owner_chat_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
    session_id: uuid.UUID | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=200),
) -> list[OwnerChatHistoryItem]:
    scope = resolve_insights_scope(
        db, current_user=current_user, restaurant_id=restaurant_id
    )
    rows = get_chat_history(db, scope=scope, session_id=session_id, limit=limit)
    return [OwnerChatHistoryItem.model_validate(row) for row in rows]


@router.delete("/chat/history", response_model=OwnerChatClearResponse)
def delete_owner_chat_history(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
    session_id: uuid.UUID | None = Query(default=None),
) -> OwnerChatClearResponse:
    scope = resolve_insights_scope(
        db, current_user=current_user, restaurant_id=restaurant_id
    )
    deleted = clear_chat_history(db, scope=scope, session_id=session_id)
    return OwnerChatClearResponse(deleted_count=deleted, cleared_session_id=session_id)


@router.get("/offer-performance", response_model=OfferPerformanceResponse)
def get_offer_performance(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    window_days: int | None = Query(default=None, ge=1),
    restaurant_id: uuid.UUID | None = Query(default=None),
    restaurant_location_id: uuid.UUID | None = Query(default=None),
) -> OfferPerformanceResponse:
    """Revenue and cost per offer: did the promotion pay for itself?

    Revenue comes from orders attributed to the offer, cost from the discount
    those orders gave away. Net revenue is revenue after discount, not profit —
    food and delivery costs are not recorded anywhere.
    """

    scope = resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )
    comparison = resolve_period_comparison(
        date_from=date_from,
        date_to=date_to,
        window_days=window_days,
    )
    period = comparison.current
    rows = fetch_offer_performance(db, scope, period)

    return OfferPerformanceResponse(
        scope=InsightsScopeResponse(
            restaurant_id=scope.restaurant_id,
            restaurant_location_id=scope.restaurant_location_id,
            timezone=comparison.timezone_name,
        ),
        period=InsightsPeriod(
            start_date=period.start_date,
            end_date=period.end_date,
            day_count=period.day_count,
            label=period.label(),
        ),
        total_gross_revenue=sum(row.gross_revenue for row in rows),
        total_discount_cost=sum(row.discount_cost for row in rows),
        total_orders=sum(row.orders for row in rows),
        offers=[
            OfferPerformanceRow(
                offer_id=row.offer_id,
                offer_name=row.offer_name,
                offer_kind=row.offer_kind,
                orders=row.orders,
                customers=row.customers,
                gross_revenue=row.gross_revenue,
                discount_cost=row.discount_cost,
                net_revenue=row.net_revenue,
                average_order_value=row.average_order_value,
                return_per_unit_discount=row.return_per_unit_discount,
                views=row.views,
                clicks=row.clicks,
                conversions=row.conversions,
                click_through_rate=row.click_through_rate,
                conversion_rate=row.conversion_rate,
            )
            for row in rows
        ],
    )


@router.get("/outcomes", response_model=list[ActionOutcomeResponse])
def get_action_outcomes(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ActionOutcomeResponse]:
    """What happened after approved actions ran.

    These are orders that used the offer, not orders it can be shown to have
    caused: there is no holdout group to compare against.
    """

    scope = resolve_insights_scope(
        db, current_user=current_user, restaurant_id=restaurant_id
    )
    return [
        ActionOutcomeResponse.model_validate(row)
        for row in list_outcomes(db, scope=scope, limit=limit)
    ]


@router.get("/recommendations", response_model=list[OwnerActionProposalResponse])
def get_recommendations(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
    restaurant_location_id: uuid.UUID | None = Query(default=None),
    action_status: list[OwnerActionStatus] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[OwnerActionProposalResponse]:
    """Recommended actions, newest run first, executable ones ranked highest."""

    scope = resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )
    rows = list_proposals(db, scope=scope, statuses=action_status, limit=limit)
    # Attach the measured result to any action that has already run, so the
    # feed shows what happened rather than only what was suggested.
    outcomes = get_outcomes_by_proposal(
        db, scope=scope, proposal_ids=[row.id for row in rows]
    )
    responses: list[OwnerActionProposalResponse] = []
    for row in rows:
        response = OwnerActionProposalResponse.model_validate(row)
        outcome = outcomes.get(row.id)
        if outcome is not None:
            response.outcome = ActionOutcomeResponse.model_validate(outcome)
        responses.append(response)
    return responses


@router.post(
    "/recommendations/{proposal_id}/approve",
    response_model=OwnerActionApprovalResponse,
)
def approve_recommendation(
    proposal_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> OwnerActionApprovalResponse:
    """Approve a recommendation, creating its offer when it is executable.

    This is the only path that turns a recommendation into something live, and
    it always requires an explicit call: nothing here runs on a schedule.
    """

    scope = resolve_insights_scope(db, current_user=current_user, restaurant_id=restaurant_id)
    proposal = get_proposal_for_scope(db, scope=scope, proposal_id=proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        )

    try:
        result = approve_proposal(
            db, proposal=proposal, decided_by_user_id=current_user.id
        )
    except ActionValidationError as error:
        # 422: the request was well formed, but the proposal cannot be executed
        # as stored — expired, over a discount cap, or the offer creation failed.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error

    if result.already_executed:
        detail = "This recommendation was already executed."
    elif result.offer_id is not None:
        detail = "Offer created."
    else:
        detail = "Recommendation acknowledged. It is advisory, so nothing was created."

    return OwnerActionApprovalResponse(
        proposal=OwnerActionProposalResponse.model_validate(result.proposal),
        offer_id=result.offer_id,
        already_executed=result.already_executed,
        detail=detail,
    )


@router.post(
    "/recommendations/{proposal_id}/reject",
    response_model=OwnerActionProposalResponse,
)
def reject_recommendation(
    proposal_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> OwnerActionProposalResponse:
    scope = resolve_insights_scope(db, current_user=current_user, restaurant_id=restaurant_id)
    proposal = get_proposal_for_scope(db, scope=scope, proposal_id=proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recommendation not found",
        )

    try:
        updated = reject_proposal(
            db, proposal=proposal, decided_by_user_id=current_user.id
        )
    except ActionValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error

    return OwnerActionProposalResponse.model_validate(updated)
