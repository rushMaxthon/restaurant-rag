"""Marketing Hub routes.

Owner-facing and owner-scoped. Every route resolves its restaurant through
`resolve_insights_scope`, which pins an owner to their own restaurant and
refuses to widen even if a different id is supplied — the same primitive the AI
Restaurant Manager uses, reused rather than re-implemented so there is one
answer to "which restaurant is this request allowed to touch".

Send, schedule execution and attribution are not in this slice. The routes
present are: reference data, reach estimation, and campaign CRUD.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.celery import celery_app
from app.config.database import get_db
from app.models.enums import (
    MarketingChannel,
    MarketingChannelFamily,
    PushNotificationCampaignStatus,
    PushNotificationEventType,
    channel_family,
)
from app.models.user import User
from app.models.user_device_token import UserDeviceToken
from app.schemas.marketing import (
    ChannelConnectRequest,
    ChannelConnectionResponse,
    ChannelEnableRequest,
    ConnectionFieldResponse,
    CampaignDraftRequest,
    CampaignGoalResponse,
    CampaignResponse,
    CampaignScheduleRequest,
    MarketingBranchResponse,
    MarketingOfferResponse,
    MarketingReferenceResponse,
    MarketingSegmentResponse,
    MessageTemplateResponse,
    ReachEstimateRequest,
    ReachEstimateResponse,
    TestSendRequest,
    TestSendResponse,
    MarketingDashboardResponse,
    CampaignEngagementRequest,
    CampaignEngagementResponse,
)
from app.services.auth import get_current_user, require_customer
from app.services.insights.scope import resolve_insights_scope
from app.services.marketing import campaigns as campaign_service
from app.services.marketing import connections as connection_service
from app.services.marketing import unsubscribe as unsubscribe_service
from app.services.marketing.consent import set_marketing_consent
from app.services.marketing.inbound import handle_marketing_reply
from app.services.marketing.providers import ProviderError, provider_for
from app.services.marketing.providers.base import BatchMember, RenderedMessage
from app.services.marketing.providers.email import undeliverable_reason
from app.services.marketing.engagement import (
    EngagementRefused,
    record_engagement,
)
from app.services.marketing.catalog import (
    FREQUENCY_CAP_PER_WEEK,
    GOALS,
    MINIMUM_SEGMENT_SIZE,
    TEMPLATES,
    branch_hours,
    list_attachable_offers,
    list_branches,
    offer_view,
)
from app.services.marketing.dashboard import build_dashboard, dashboard_view
from app.services.marketing.dispatch import render_merge_fields
from app.services.marketing.reach import estimate_reach, unavailable_result
from app.services.marketing.segments import (
    SEGMENT_RULES,
    SegmentUnavailable,
    count_segment_members,
    resolve_marketing_app_client_id,
)
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/marketing", tags=["Marketing"])


def _scope(
    db: Session,
    current_user: User,
    restaurant_id: uuid.UUID | None = None,
):
    return resolve_insights_scope(
        db,
        current_user=current_user,
        restaurant_id=restaurant_id,
    )


def _validation_error(exc: campaign_service.CampaignValidationError) -> HTTPException:
    """A lifecycle refusal, as a 409 carrying the owner-readable reason.

    409 rather than 400: the request was well formed, the campaign is simply
    not in a state where it can do this. The message is written for the owner
    and is surfaced verbatim, so it must never contain a status enum or a
    column name.
    """

    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# --- reference -------------------------------------------------------------


@router.get("/reference", response_model=MarketingReferenceResponse)
def get_marketing_reference(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> MarketingReferenceResponse:
    """Everything the wizard needs before a draft exists.

    Segment member counts are computed here, across all branches, so the
    segment cards show a real number the moment the picker opens rather than
    after a second round trip.
    """

    scope = _scope(db, current_user, restaurant_id)
    computed_at = datetime.now(UTC)

    branches = list_branches(db, scope.restaurant_id)
    hours = branch_hours(db, [branch.id for branch in branches])

    try:
        app_client_id = resolve_marketing_app_client_id(db, scope.restaurant_id)
    except SegmentUnavailable:
        # The restaurant has no app of its own. Reference data still renders —
        # the owner can look around — but every segment is honestly zero, and
        # the reach step is what explains why.
        app_client_id = None

    segments = [
        MarketingSegmentResponse(
            key=rule.key,
            name=rule.name,
            definition=rule.definition,
            total_members=(
                count_segment_members(
                    db,
                    key=rule.key,
                    restaurant_id=scope.restaurant_id,
                    app_client_id=app_client_id,
                    now=computed_at,
                )
                if app_client_id is not None
                else 0
            ),
            members_by_branch=(
                {
                    str(branch.id): count_segment_members(
                        db,
                        key=rule.key,
                        restaurant_id=scope.restaurant_id,
                        app_client_id=app_client_id,
                        branch_ids=[branch.id],
                        now=computed_at,
                    )
                    for branch in branches
                }
                if app_client_id is not None
                else {}
            ),
            computed_at=computed_at,
        )
        for rule in SEGMENT_RULES
    ]

    return MarketingReferenceResponse(
        goals=[
            CampaignGoalResponse(
                key=goal.key,
                label=goal.label,
                description=goal.description,
                default_segment=goal.default_segment,
                default_channels=list(goal.default_channels),
                success_metric=goal.success_metric,
                suggests_offer=goal.suggests_offer,
            )
            for goal in GOALS
        ],
        segments=segments,
        branches=[
            MarketingBranchResponse(
                id=branch.id,
                branch_name=branch.branch_name,
                city=branch.city,
                state=branch.state,
                is_active=branch.is_active,
                opens_at=hours[branch.id].opens_at,
                closes_at=hours[branch.id].closes_at,
            )
            for branch in branches
        ],
        offers=[
            MarketingOfferResponse(**offer_view(offer))
            for offer in list_attachable_offers(db, scope.restaurant_id)
        ],
        templates=[
            MessageTemplateResponse(
                id=template.id,
                name=template.name,
                goal=template.goal,
                channel=template.channel,
                title=template.title,
                body=template.body,
            )
            for template in TEMPLATES
        ],
        minimum_segment_size=MINIMUM_SEGMENT_SIZE,
        frequency_cap_per_week=FREQUENCY_CAP_PER_WEEK,
        timezone=settings.business_timezone,
    )


# --- reach -----------------------------------------------------------------


@router.post("/reach-estimate", response_model=ReachEstimateResponse)
def post_reach_estimate(
    payload: ReachEstimateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ReachEstimateResponse:
    """How many people this draft would reach, and what would stop it.

    Recomputed from scratch on every call. Nothing about the estimate is
    cached, because every input the owner can change moves the answer and a
    stale reach number is worse than a slow one.
    """

    scope = _scope(db, current_user, restaurant_id)

    try:
        app_client_id = resolve_marketing_app_client_id(db, scope.restaurant_id)
    except SegmentUnavailable as exc:
        result = unavailable_result(str(exc))
        return _reach_response(result)

    channels = payload.channels or [MarketingChannel.PUSH]
    result = estimate_reach(
        db,
        restaurant_id=scope.restaurant_id,
        app_client_id=app_client_id,
        segment_key=payload.segment_key,
        branch_ids=payload.branch_ids,
        channels=channels,
        send_at=payload.send_at,
    )
    return _reach_response(result)


def _reach_response(result) -> ReachEstimateResponse:
    """Serialise a reach result.

    `reachable_user_ids` is deliberately dropped. The owner is entitled to know
    how many of their customers can be reached; they are not entitled to a list
    of which accounts those are, and an endpoint that returned one would be a
    customer-export disguised as an estimate.
    """

    return ReachEstimateResponse(
        segment_members=result.segment_members,
        audience_size=result.audience_size,
        channels=[
            {
                "channel": channel.channel,
                "available": channel.available,
                "unavailable_reason": channel.unavailable_reason,
                "reachable": channel.reachable,
                "blockers": channel.blockers,
                "estimated_cost": channel.estimated_cost,
            }
            for channel in result.channels
        ],
        notices=[
            {
                "id": notice.id,
                "tone": notice.tone.value,
                "title": notice.title,
                "description": notice.description,
            }
            for notice in result.notices
        ],
        minimum_segment_size=result.minimum_segment_size,
    )


# --- campaigns -------------------------------------------------------------


@router.get("/dashboard", response_model=MarketingDashboardResponse)
def get_marketing_dashboard(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> MarketingDashboardResponse:
    """The Hub home's figures, every one of them attributed rather than guessed.

    Listed before `/campaigns` for readability only; the paths cannot collide.
    """

    scope = _scope(db, current_user, restaurant_id)
    view = build_dashboard(db, restaurant_id=scope.restaurant_id)
    return MarketingDashboardResponse(**dashboard_view(view))


@router.get("/campaigns", response_model=list[CampaignResponse])
def get_campaigns(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
    campaign_status: Annotated[PushNotificationCampaignStatus | None, Query(alias="status")] = None,
) -> list[CampaignResponse]:
    scope = _scope(db, current_user, restaurant_id)
    rows = campaign_service.list_campaigns(
        db,
        restaurant_id=scope.restaurant_id,
        statuses=[campaign_status] if campaign_status else None,
    )
    return [CampaignResponse(**campaign_service.campaign_view(row)) for row in rows]


@router.post(
    "/campaigns",
    response_model=CampaignResponse,
    status_code=status.HTTP_200_OK,
)
def post_campaign_draft(
    payload: CampaignDraftRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CampaignResponse:
    """Create or update a draft.

    200 rather than 201 on create: the wizard saves the same draft repeatedly
    as the owner moves between steps, and a status code that changed on the
    first call only would be noise the client has to special-case.
    """

    scope = _scope(db, current_user, restaurant_id)
    try:
        campaign = campaign_service.save_draft(
            db,
            payload=payload,
            restaurant_id=scope.restaurant_id,
            created_by_user_id=current_user.id,
        )
    except campaign_service.CampaignValidationError as exc:
        raise _validation_error(exc) from exc
    return CampaignResponse(**campaign_service.campaign_view(campaign))


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
def get_campaign_detail(
    campaign_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CampaignResponse:
    scope = _scope(db, current_user, restaurant_id)
    campaign = campaign_service.get_campaign(
        db,
        campaign_id=campaign_id,
        restaurant_id=scope.restaurant_id,
    )
    # The session is passed here and nowhere else: this is the report screen,
    # and attribution costs two queries the campaign list must not pay per row.
    return CampaignResponse(**campaign_service.campaign_view(campaign, db=db))


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_campaign(
    campaign_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Response:
    scope = _scope(db, current_user, restaurant_id)
    try:
        campaign_service.delete_draft(
            db,
            campaign_id=campaign_id,
            restaurant_id=scope.restaurant_id,
        )
    except campaign_service.CampaignValidationError as exc:
        raise _validation_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/campaigns/{campaign_id}/duplicate", response_model=CampaignResponse)
def post_duplicate_campaign(
    campaign_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CampaignResponse:
    scope = _scope(db, current_user, restaurant_id)
    campaign = campaign_service.duplicate_campaign(
        db,
        campaign_id=campaign_id,
        restaurant_id=scope.restaurant_id,
        created_by_user_id=current_user.id,
    )
    return CampaignResponse(**campaign_service.campaign_view(campaign))


@router.post("/campaigns/{campaign_id}/cancel", response_model=CampaignResponse)
def post_cancel_campaign(
    campaign_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CampaignResponse:
    scope = _scope(db, current_user, restaurant_id)
    try:
        campaign = campaign_service.cancel_campaign(
            db,
            campaign_id=campaign_id,
            restaurant_id=scope.restaurant_id,
        )
    except campaign_service.CampaignValidationError as exc:
        raise _validation_error(exc) from exc
    return CampaignResponse(**campaign_service.campaign_view(campaign))


@router.post("/campaigns/{campaign_id}/schedule", response_model=CampaignResponse)
def post_schedule_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignScheduleRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CampaignResponse:
    """Queue a campaign for a future time.

    The pre-send checks run here as well as in the wizard, because the draft
    the client submitted may not be the draft the server has: branch, segment
    and consent can all have moved since the owner last saw a reach estimate.
    A blocking notice refuses the schedule outright, and says which one.

    Nothing executes the schedule yet — that is the dispatcher, which is the
    next slice. A campaign scheduled today simply sits in SCHEDULED until it
    exists.
    """

    scope = _scope(db, current_user, restaurant_id)
    campaign = campaign_service.get_campaign(
        db,
        campaign_id=campaign_id,
        restaurant_id=scope.restaurant_id,
    )

    try:
        app_client_id = resolve_marketing_app_client_id(db, scope.restaurant_id)
    except SegmentUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    result = estimate_reach(
        db,
        restaurant_id=scope.restaurant_id,
        app_client_id=app_client_id,
        segment_key=campaign_service.MarketingSegmentKey(campaign.segment_key),
        branch_ids=[uuid.UUID(value) for value in (campaign.branch_ids or [])],
        channels=[MarketingChannel(value) for value in (campaign.channels or [])],
        send_at=payload.send_at,
        timezone_name=campaign.timezone,
    )
    if result.blocked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.blocking_reason(),
        )

    try:
        scheduled = campaign_service.schedule_campaign(
            db,
            campaign_id=campaign_id,
            restaurant_id=scope.restaurant_id,
            send_at=payload.send_at,
        )
    except campaign_service.CampaignValidationError as exc:
        raise _validation_error(exc) from exc

    # The audience the schedule was accepted against, so the list shows a real
    # number before anything is sent. Recomputed at dispatch.
    scheduled.estimated_recipient_count = result.audience_size
    db.add(scheduled)
    db.commit()
    db.refresh(scheduled)

    return CampaignResponse(**campaign_service.campaign_view(scheduled))


@router.post("/campaigns/{campaign_id}/send", response_model=CampaignResponse)
def post_send_campaign(
    campaign_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CampaignResponse:
    """Send a campaign now.

    Returns as soon as the campaign is claimed, with the campaign in SENDING —
    the send itself runs on the notifications queue. The owner's browser must
    not be the thing holding a multi-thousand-customer dispatch open, and a
    request that returned only when the last push landed would lose the send
    if they navigated away.

    The pre-send checks run here as well as in the wizard for the same reason
    they run on schedule: the draft the client is looking at may not be the
    draft the server has. The audience is then recomputed a third time inside
    dispatch, which is the only count that decides who is actually messaged.
    """

    scope = _scope(db, current_user, restaurant_id)
    campaign = campaign_service.get_campaign(
        db,
        campaign_id=campaign_id,
        restaurant_id=scope.restaurant_id,
    )

    try:
        app_client_id = resolve_marketing_app_client_id(db, scope.restaurant_id)
    except SegmentUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    if not campaign.segment_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Choose who this campaign is for before sending it.",
        )

    result = estimate_reach(
        db,
        restaurant_id=scope.restaurant_id,
        app_client_id=app_client_id,
        segment_key=campaign_service.MarketingSegmentKey(campaign.segment_key),
        branch_ids=[uuid.UUID(value) for value in (campaign.branch_ids or [])],
        channels=[MarketingChannel(value) for value in (campaign.channels or [])],
        # No send_at: sending now means quiet hours are judged against now.
        send_at=None,
        timezone_name=campaign.timezone,
    )
    if result.blocked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=result.blocking_reason(),
        )

    try:
        claimed = campaign_service.claim_for_sending(
            db,
            campaign_id=campaign_id,
            restaurant_id=scope.restaurant_id,
        )
    except campaign_service.CampaignValidationError as exc:
        raise _validation_error(exc) from exc

    claimed.estimated_recipient_count = result.audience_size
    db.add(claimed)
    db.commit()
    db.refresh(claimed)

    try:
        celery_app.send_task(
            "app.tasks.marketing.send_marketing_campaign",
            args=[str(claimed.id)],
        )
    except Exception as exc:  # noqa: BLE001
        # A claimed campaign with no worker behind it would sit in SENDING
        # forever, and SENDING has no way back except SENT or FAILED. Putting
        # it down here is what keeps the owner's retry button meaningful.
        logger.exception("Could not queue marketing send id=%s", claimed.id)
        campaign_service.mark_send_failed(
            db,
            campaign=claimed,
            reason="The send could not be queued. Try again in a moment.",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The send could not be queued. Try again in a moment.",
        ) from exc

    return CampaignResponse(**campaign_service.campaign_view(claimed))


@router.post("/test-send", response_model=TestSendResponse)
def post_test_send(
    payload: TestSendRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> TestSendResponse:
    """Send the campaign copy to the signed-in staff member, and nobody else.

    Deliberately not "send to an arbitrary address": a test send that could
    name any recipient is a way to push a message to a customer outside every
    consent and frequency rule this module enforces. The only audience is the
    person pressing the button, on whatever address their own account holds.

    **A public post cannot be tested.** There is no private Instagram. Sending
    a push instead — which is what a channel-blind test send would do — would
    let an owner conclude Instagram works.
    """

    scope = _scope(db, current_user, restaurant_id)
    channel = payload.channel

    if channel_family(channel) is MarketingChannelFamily.SOCIAL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"A {channel.value.title()} post cannot be tested privately — "
                "anything posted is public. Use the preview instead."
            ),
        )

    connection = connection_service.get_connection(
        db, restaurant_id=scope.restaurant_id, channel=channel
    )
    try:
        provider = provider_for(channel, connection)
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc

    # Push is the one channel whose address is not on the user row.
    if channel is MarketingChannel.PUSH:
        addresses = [
            token.fcm_token
            for token in db.scalars(
                select(UserDeviceToken).where(
                    UserDeviceToken.user_id == current_user.id,
                    UserDeviceToken.is_active.is_(True),
                )
            ).all()
        ]
        empty_detail = (
            "No device is registered for your account. Sign in to the app on "
            "your phone, then try the test again."
        )
    else:
        addresses = provider.addresses_for(current_user)
        empty_detail = (
            f"Your account has no {'mobile number' if channel in (MarketingChannel.SMS, MarketingChannel.WHATSAPP) else 'email address'} "
            "on file, so there is nowhere to send the test."
        )

    if not addresses:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=empty_detail)

    # An address that can never receive mail is refused rather than attempted.
    #
    # Every seeded account here is `@example.com`, which has no mail server.
    # Posting to it succeeds — the provider accepts the message — and the
    # bounce arrives minutes later in the *sending* mailbox, so the owner gets
    # a delivery failure for an address they never typed and cannot place.
    # Refusing now turns that into an immediate, accurate sentence, and keeps
    # repeated bounces off the sending domain's reputation.
    #
    # Email only: push has no address to validate, and the SMS and WhatsApp
    # equivalents would need a phone-number rule rather than a domain one.
    if channel is MarketingChannel.EMAIL:
        reason = undeliverable_reason(addresses[0])
        if reason:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"{reason} A test goes to the address on your own staff account, "
                    "not to the address the channel sends from — so sign in with a "
                    "real one, or change this account's email."
                ),
            )

    first_name = (current_user.full_name or "").split(" ")[0] or None
    title = render_merge_fields(payload.title, first_name=first_name, branch=None)
    body = render_merge_fields(payload.body, first_name=first_name, branch=None)

    if not settings.enable_marketing_dispatch:
        # Same switch as a real send. A test that delivered while the product
        # was configured not to send would be the one path that escapes the
        # flag, which is the whole point of the flag.
        return TestSendResponse(
            delivered=False,
            device_count=len(addresses),
            detail=(
                "Sending is switched off in this environment, so nothing was "
                f"delivered. The message would read: {title} — {body}"
            ),
        )

    member = BatchMember(user_id=current_user.id, addresses=addresses)
    try:
        result = provider.send(
            [member],
            message=RenderedMessage(
                title=title,
                body=body,
                data={"notification_type": "marketing_test", "campaign_id": ""},
                # A test has no campaign, so no unsubscribe token can be
                # minted for it — and it is going to the owner's own account,
                # who is not being marketed to.
                extra={},
            ),
        )
    except ProviderError as exc:
        logger.warning("Marketing test send refused user_id=%s: %s", current_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Marketing test send failed user_id=%s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The test message could not be sent: {exc}",
        ) from exc

    outcome = result.outcomes[0] if result.outcomes else None
    delivered = bool(outcome and outcome.delivered)

    if delivered:
        # The credentials just worked against the real provider, which is the
        # only proof this system can have. The picker stops saying "connected
        # but never verified".
        connection_service.mark_verified(
            db, restaurant_id=scope.restaurant_id, channel=channel
        )

    return TestSendResponse(
        delivered=delivered,
        device_count=len(addresses),
        detail=(
            f"Sent to you on {channel.value.title()}."
            if delivered
            else (outcome.reason if outcome and outcome.reason else "It was not delivered.")
        ),
    )


# --- inbound SMS -----------------------------------------------------------


@router.post("/sms/inbound", include_in_schema=False)
async def post_sms_inbound(
    request: Request,
    token_header: Annotated[str | None, Header(alias="X-Marketing-Token")] = None,
    token_query: Annotated[str | None, Query(alias="token")] = None,
) -> dict[str, str]:
    """An SMS gateway handing back a reply, which is almost always "STOP".

    Every marketing text this product sends ends "Reply STOP to opt out",
    and the operator delivers that reply here. Without this endpoint the
    footer is a promise the system cannot keep — which is worse than not
    offering one, because the customer did the thing they were told to do.

    **Deliberately tolerant about shape.** There is no inbound standard across
    SMS aggregators the way Meta and Stripe have one: some post JSON, some
    post a form, and the two fields are variously `from`/`sender`/`msisdn` and
    `text`/`body`/`message`. Reading whichever arrived is the difference
    between this working for the operator a restaurant already pays and
    working only for the one we happened to test against.

    **Deliberately strict about the secret.** An unauthenticated route here
    could opt any customer out by guessing a phone number, so an unset secret
    refuses everything rather than accepting everything.

    Answers 200 to anything it accepts, including a message that was not a
    STOP. A gateway that reads a non-200 as failure will redeliver, and a
    redelivered opt-out is noise, not safety.
    """

    expected = (settings.marketing_sms_inbound_secret or "").strip()
    supplied = (token_header or token_query or "").strip()
    if not expected or not secrets.compare_digest(expected, supplied):
        # Constant-time, and the same refusal whether the secret is unset or
        # merely wrong — the difference is not the caller's business.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not authorised."
        )

    payload: dict = {}
    try:
        body = await request.body()
        if body:
            content_type = (request.headers.get("content-type") or "").lower()
            if "json" in content_type:
                payload = json.loads(body)
            else:
                payload = dict(await request.form())
    except (ValueError, TypeError):
        logger.warning("Inbound SMS payload could not be read")
        return {"status": "ignored"}

    if not isinstance(payload, dict):
        return {"status": "ignored"}

    def _first(*names: str) -> str:
        for name in names:
            value = payload.get(name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    from_number = _first("from", "sender", "msisdn", "source", "phone")
    text = _first("text", "body", "message", "content")
    if not from_number or not text:
        return {"status": "ignored"}

    handled = handle_marketing_reply(from_number, text, source="sms")
    return {"status": "handled" if handled else "ignored"}


# --- channel connections ---------------------------------------------------


def _connection_response(view) -> ChannelConnectionResponse:
    return ChannelConnectionResponse(
        channel=view.channel,
        family=view.family,
        connected=view.connected,
        status=view.status,
        config=view.config,
        identity=view.identity,
        connected_at=view.connected_at,
        verified_at=view.verified_at,
        last_error=view.last_error,
        requirements=[
            ConnectionFieldResponse(
                key=spec.key,
                label=spec.label,
                example=spec.example,
                secret=spec.secret,
                required=spec.required,
                help=spec.help,
            )
            for spec in view.requirements
        ],
    )


@router.get("/channels", response_model=list[ChannelConnectionResponse])
def get_channels(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ChannelConnectionResponse]:
    """Every channel and whether this restaurant can send on it.

    The channel picker's source of truth. It used to be a constant in the
    frontend that could only say "not connected yet", which meant a channel
    that HAD been connected still rendered as unavailable.
    """

    scope = _scope(db, current_user, restaurant_id)
    return [
        _connection_response(view)
        for view in connection_service.all_views(db, restaurant_id=scope.restaurant_id)
    ]


@router.put("/channels/{channel}", response_model=ChannelConnectionResponse)
def put_channel_connection(
    channel: MarketingChannel,
    payload: ChannelConnectRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ChannelConnectionResponse:
    """Save what a channel needs, keeping secrets the owner did not retype.

    A connect form cannot show a stored token, so an owner correcting their
    sender name would otherwise blank the API key by leaving its field empty
    — and would not find out until the next send failed.
    """

    scope = _scope(db, current_user, restaurant_id)
    try:
        connection = connection_service.connect(
            db,
            restaurant_id=scope.restaurant_id,
            channel=channel,
            values=payload.values,
        )
    except connection_service.ConnectionError_ as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return _connection_response(connection_service.view_for(channel, connection))


@router.post("/channels/{channel}/enabled", response_model=ChannelConnectionResponse)
def post_channel_enabled(
    channel: MarketingChannel,
    payload: ChannelEnableRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ChannelConnectionResponse:
    """Pause or resume a channel without losing how it was set up."""

    scope = _scope(db, current_user, restaurant_id)
    try:
        connection = connection_service.set_enabled(
            db,
            restaurant_id=scope.restaurant_id,
            channel=channel,
            enabled=payload.enabled,
        )
    except connection_service.ConnectionError_ as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _connection_response(connection_service.view_for(channel, connection))


@router.delete("/channels/{channel}", status_code=status.HTTP_204_NO_CONTENT)
def delete_channel_connection(
    channel: MarketingChannel,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Response:
    """Forget the channel, credentials included.

    Idempotent: disconnecting a channel that was never connected is a 204,
    not a 404. The owner asked for it to be gone and it is gone.
    """

    scope = _scope(db, current_user, restaurant_id)
    connection_service.disconnect(
        db, restaurant_id=scope.restaurant_id, channel=channel
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- engagement ------------------------------------------------------------


@router.post("/engagement", response_model=CampaignEngagementResponse)
def post_campaign_engagement(
    payload: CampaignEngagementRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> CampaignEngagementResponse:
    """Report that the signed-in customer opened, tapped or opted out of a push.

    Customer-authenticated rather than open: the event is attributed to a
    person, and an unauthenticated endpoint taking a campaign id would let
    anyone move another restaurant's numbers. The user comes from the token,
    never from the body.

    UNSUBSCRIBED does two things at once and both matter — it opts the customer
    out, and it records which message prompted it. An opt-out rate per campaign
    is how an owner learns that a piece of copy cost them their list.
    """

    event_type = PushNotificationEventType(payload.event)
    try:
        recorded = record_engagement(
            db,
            campaign_id=payload.campaign_id,
            user=current_user,
            event_type=event_type,
        )
    except EngagementRefused as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    if event_type is PushNotificationEventType.UNSUBSCRIBED:
        set_marketing_consent(db, user=current_user, opted_in=False)

    return CampaignEngagementResponse(
        recorded=recorded,
        marketing_opt_in=current_user.marketing_opt_in,
    )


# --- unsubscribe -----------------------------------------------------------

#: Deliberately plain. This page is reached from a lock screen by someone who
#: has decided to stop hearing from a restaurant, and anything that looks like
#: another marketing surface is the wrong answer to that.
_UNSUB_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 0;
         padding: 48px 24px; background: #f7f5f0; color: #1b1b1b;
         text-align: center; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 12px; }}
  p {{ font-size: 1.05rem; line-height: 1.5; margin: 0 0 24px; color: #4a4a4a; }}
  button {{ font: inherit; font-weight: 600; padding: 14px 26px; border: 0;
           border-radius: 999px; background: #1f8f4e; color: #fff;
           cursor: pointer; }}
</style></head>
<body><h1>{title}</h1><p>{body}</p>{action}</body></html>"""


def _unsub_page(title: str, body: str, action: str = "") -> HTMLResponse:
    return HTMLResponse(_UNSUB_PAGE.format(title=title, body=body, action=action))


@router.get("/unsubscribe/{token}", include_in_schema=False)
def get_unsubscribe(token: str) -> HTMLResponse:
    """Ask before opting anyone out.

    A GET must not change anything here. Mail clients, chat previews and link
    scanners fetch URLs with no human involved, so a GET that unsubscribed
    would quietly opt people out of messages they never even opened. The form
    below is one tap, and it is what makes this link safe to put in an email in
    Phase 2.
    """

    if unsubscribe_service.read_token(token) is None:
        return _unsub_page(
            "This link is not valid",
            "It may have been copied incompletely. You can change marketing "
            "messages at any time in the app, under Preferences.",
        )

    return _unsub_page(
        "Stop marketing messages?",
        "You will still get updates about your orders — those are not "
        "marketing and are not affected.",
        '<form method="post"><button type="submit">Yes, unsubscribe me</button></form>',
    )


@router.post("/unsubscribe/{token}", include_in_schema=False)
def post_unsubscribe(
    token: str,
    db: Annotated[Session, Depends(get_db)],
) -> HTMLResponse:
    """Perform the opt-out named by the token.

    Unauthenticated by necessity — the person is in a browser from a phone
    notification and may have no session. The signature is the credential, and
    it only ever moves consent in the safe direction.
    """

    parsed = unsubscribe_service.read_token(token)
    if parsed is None:
        return _unsub_page(
            "This link is not valid",
            "Nothing has been changed. You can manage marketing messages in "
            "the app, under Preferences.",
        )

    user_id, campaign_id = parsed
    user = db.get(User, user_id)
    if user is None:
        # A deleted account is already unsubscribed in every sense that
        # matters, and saying so would confirm the id belonged to someone.
        return _unsub_page(
            "You are unsubscribed",
            "You will not receive marketing messages from this restaurant.",
        )

    if user.marketing_opt_in:
        set_marketing_consent(db, user=user, opted_in=False)

    # Attributed to the campaign that prompted it, which is what lets an owner
    # see that a particular message cost them subscribers. Best-effort: the
    # opt-out above is the part that must not fail.
    try:
        record_engagement(
            db,
            campaign_id=campaign_id,
            user=user,
            event_type=PushNotificationEventType.UNSUBSCRIBED,
        )
    except EngagementRefused:
        logger.info(
            "Unsubscribe not attributable to campaign=%s user=%s", campaign_id, user_id
        )

    return _unsub_page(
        "You are unsubscribed",
        "You will not receive marketing messages from this restaurant. Order "
        "updates are unaffected. You can turn this back on in the app at any "
        "time.",
    )
