"""Campaign persistence and lifecycle.

Rows live in `push_notification_campaigns` with `kind = MARKETING`. Everything
this module reads is filtered on that plus `restaurant_id`, so a tenant can
only ever see its own campaigns and never sees a transactional order push.

Two rules the whole module is built around:

**A draft saves whatever it has.** The wizard has five steps and saves on every
one. Refusing to persist an incomplete draft would lose the owner's work every
time they stepped away mid-flow. Validation that decides whether a campaign can
*go out* belongs at send time, against data that may have moved since.

**Status transitions are explicit.** `PushNotificationCampaignStatus` is not
linear the way `OrderStatus` is, but the legal moves are still a fixed set, and
`_assert_transition` is the only place they are written down. A campaign that
has sent is immutable; letting an owner edit one after the fact would silently
rewrite the message its report is about.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    MarketingCampaignGoal,
    MarketingChannel,
    MarketingChannelFamily,
    MarketingDeepLink,
    MarketingSegmentKey,
    PushNotificationAudience,
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
    PushNotificationDeliveryType,
    channel_family,
)
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.restaurant_location import RestaurantLocation
from app.schemas.marketing import CampaignDraftRequest
from app.services.marketing.attribution import (
    attribution_view,
    build_attribution,
    build_social_attribution,
    failure_reason_view,
    social_post_view,
)
from app.services.marketing.catalog import list_attachable_offers

logger = logging.getLogger(__name__)
settings = get_settings()


Status = PushNotificationCampaignStatus

#: What a campaign in each status may become. Absent keys are terminal.
#:
#: SENT and CANCELLED are deliberately terminal, and FAILED is deliberately
#: not: a send that failed for a transient reason should be retryable without
#: the owner rebuilding it, and retrying rewrites no history because a failed
#: campaign has no report.
ALLOWED_TRANSITIONS: dict[Status, set[Status]] = {
    Status.DRAFT: {Status.SCHEDULED, Status.SENDING, Status.CANCELLED},
    Status.SCHEDULED: {Status.SENDING, Status.CANCELLED, Status.DRAFT},
    Status.SENDING: {Status.SENT, Status.FAILED},
    Status.FAILED: {Status.DRAFT, Status.SENDING, Status.SCHEDULED},
}

#: Statuses whose content may still be edited. Once a campaign has left this
#: set, the message customers received is a matter of record.
EDITABLE_STATUSES = {Status.DRAFT, Status.SCHEDULED, Status.FAILED}


class CampaignValidationError(Exception):
    """A campaign cannot do what was asked of it, with an owner-readable reason."""


def _assert_transition(campaign: PushNotificationCampaign, target: Status) -> None:
    allowed = ALLOWED_TRANSITIONS.get(campaign.status, set())
    if target not in allowed:
        raise CampaignValidationError(
            f"A {campaign.status.value.lower()} campaign cannot be "
            f"{target.value.lower()}."
        )


def _assert_editable(campaign: PushNotificationCampaign) -> None:
    if campaign.status not in EDITABLE_STATUSES:
        raise CampaignValidationError(
            "This campaign has already gone out and can no longer be edited. "
            "Duplicate it to send something similar."
        )


# --- reading ---------------------------------------------------------------


def _marketing_scope(restaurant_id: uuid.UUID) -> list:
    return [
        PushNotificationCampaign.restaurant_id == restaurant_id,
        PushNotificationCampaign.kind == PushNotificationCampaignKind.MARKETING,
    ]


def list_campaigns(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    statuses: list[Status] | None = None,
    limit: int = 100,
) -> list[PushNotificationCampaign]:
    query = (
        select(PushNotificationCampaign)
        .where(*_marketing_scope(restaurant_id))
        .order_by(PushNotificationCampaign.created_at.desc())
        .limit(limit)
    )
    if statuses:
        query = query.where(PushNotificationCampaign.status.in_(statuses))
    return list(db.scalars(query).all())


def get_campaign(
    db: Session,
    *,
    campaign_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> PushNotificationCampaign:
    """One campaign, or 404.

    404 rather than 403 when it belongs to another restaurant, so campaign ids
    cannot be used to probe what other tenants have.
    """

    campaign = db.scalar(
        select(PushNotificationCampaign).where(
            PushNotificationCampaign.id == campaign_id,
            *_marketing_scope(restaurant_id),
        )
    )
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Campaign not found",
        )
    return campaign


# --- writing ---------------------------------------------------------------


def _validate_branches(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    branch_ids: list[uuid.UUID],
) -> None:
    """Every branch named must belong to this restaurant.

    The UI only ever offers this restaurant's branches, which is exactly why
    this is checked here too — a UI guard is not a rule. Without it a crafted
    request could scope a campaign to a competitor's branch and read its
    customer count back out of the reach estimate.
    """

    if not branch_ids:
        return

    owned = set(
        db.scalars(
            select(RestaurantLocation.id).where(
                RestaurantLocation.id.in_(branch_ids),
                RestaurantLocation.restaurant_id == restaurant_id,
            )
        ).all()
    )
    unknown = [str(branch_id) for branch_id in branch_ids if branch_id not in owned]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more branches do not belong to this restaurant",
        )


def _validate_offer(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    offer_id: uuid.UUID | None,
) -> None:
    if offer_id is None:
        return
    attachable = {offer.id for offer in list_attachable_offers(db, restaurant_id)}
    if offer_id not in attachable:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That offer is not available to attach to a campaign",
        )


def save_draft(
    db: Session,
    *,
    payload: CampaignDraftRequest,
    restaurant_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
) -> PushNotificationCampaign:
    """Create or update a draft from any step of the wizard."""

    _validate_branches(db, restaurant_id=restaurant_id, branch_ids=payload.branch_ids)
    _validate_offer(db, restaurant_id=restaurant_id, offer_id=payload.offer_id)

    if payload.id is not None:
        campaign = get_campaign(db, campaign_id=payload.id, restaurant_id=restaurant_id)
        _assert_editable(campaign)
    else:
        campaign = PushNotificationCampaign(
            id=uuid.uuid4(),
            restaurant_id=restaurant_id,
            created_by_user_id=created_by_user_id,
            kind=PushNotificationCampaignKind.MARKETING,
            # SEGMENT, always. The role-based audiences belong to the admin
            # broadcast path; a marketing campaign's recipients are computed.
            audience=PushNotificationAudience.SEGMENT,
            status=Status.DRAFT,
        )

    campaign.name = payload.name.strip()
    campaign.goal = payload.goal.value
    campaign.segment_key = payload.segment_key.value
    campaign.branch_ids = [str(branch_id) for branch_id in payload.branch_ids]
    campaign.channels = [channel.value for channel in payload.channels]
    campaign.offer_id = payload.offer_id
    campaign.title = payload.content.title.strip()
    campaign.message = payload.content.body.strip()
    campaign.deep_link = payload.content.deep_link.value
    campaign.template_key = payload.content.template_id
    # The per-channel tail rides in `data_payload`, which the transactional
    # push path also uses - so it is namespaced rather than assigned over. A
    # marketing campaign has never had anything else in there, but the column
    # is shared and a future writer should not have to know about this one.
    campaign.data_payload = {
        **(campaign.data_payload or {}),
        "content_extra": dict(payload.content.extra),
    }
    campaign.timezone = payload.schedule.timezone
    campaign.last_step = payload.last_step

    if payload.schedule.mode == "SCHEDULED":
        campaign.delivery_type = PushNotificationDeliveryType.SCHEDULED
        campaign.scheduled_for = payload.schedule.send_at
    else:
        campaign.delivery_type = PushNotificationDeliveryType.INSTANT
        campaign.scheduled_for = None

    # A draft edited after a failed send goes back to being a draft. Leaving it
    # FAILED would show a red campaign in the list that the owner has already
    # fixed.
    if campaign.status == Status.FAILED:
        campaign.status = Status.DRAFT
        campaign.last_error = None

    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    logger.info(
        "Marketing campaign saved id=%s restaurant_id=%s status=%s step=%s",
        campaign.id,
        restaurant_id,
        campaign.status.value,
        campaign.last_step,
    )
    return campaign


def delete_draft(
    db: Session,
    *,
    campaign_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> None:
    """Delete a campaign that never went out.

    Only a draft. A sent campaign is the record of something customers actually
    received, and a scheduled one is cancelled rather than deleted so the
    cancellation itself is visible.
    """

    campaign = get_campaign(db, campaign_id=campaign_id, restaurant_id=restaurant_id)
    if campaign.status != Status.DRAFT:
        raise CampaignValidationError(
            "Only a draft can be deleted. Cancel the campaign instead."
        )
    db.delete(campaign)
    db.commit()
    logger.info("Marketing campaign deleted id=%s restaurant_id=%s", campaign_id, restaurant_id)


def duplicate_campaign(
    db: Session,
    *,
    campaign_id: uuid.UUID,
    restaurant_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
) -> PushNotificationCampaign:
    """Copy a campaign's content into a fresh draft.

    Content and targeting carry over; schedule, status, counters, errors and
    every delivery figure do not. A duplicate is a new campaign that happens to
    say the same thing — inheriting the original's numbers would attribute one
    send's results to two rows.
    """

    original = get_campaign(db, campaign_id=campaign_id, restaurant_id=restaurant_id)

    copy = PushNotificationCampaign(
        id=uuid.uuid4(),
        restaurant_id=restaurant_id,
        created_by_user_id=created_by_user_id,
        kind=PushNotificationCampaignKind.MARKETING,
        audience=PushNotificationAudience.SEGMENT,
        status=Status.DRAFT,
        name=_copy_name(db, restaurant_id, original.name or "Campaign"),
        goal=original.goal,
        segment_key=original.segment_key,
        branch_ids=list(original.branch_ids or []),
        channels=list(original.channels or []),
        offer_id=original.offer_id,
        title=original.title,
        message=original.message,
        deep_link=original.deep_link,
        template_key=original.template_key,
        # The channel-specific half of the content - the photo, the hashtags,
        # the promo code. Copying the title and leaving this behind would give
        # an Instagram duplicate a caption and no image, which is not a post.
        data_payload=dict(original.data_payload or {}),
        timezone=original.timezone,
        delivery_type=PushNotificationDeliveryType.INSTANT,
        last_step=original.last_step,
        attribution_window_days=original.attribution_window_days,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    logger.info("Marketing campaign duplicated from=%s to=%s", campaign_id, copy.id)
    return copy


def _copy_name(db: Session, restaurant_id: uuid.UUID, base: str) -> str:
    """"X" becomes "X (copy)", then "X (copy 2)".

    Named rather than left identical because the campaign list is how an owner
    finds a campaign, and two rows called the same thing make it unusable.
    """

    existing = set(
        db.scalars(
            select(PushNotificationCampaign.name).where(*_marketing_scope(restaurant_id))
        ).all()
    )
    candidate = f"{base} (copy)"
    index = 2
    while candidate in existing:
        candidate = f"{base} (copy {index})"
        index += 1
    return candidate[:255]


def cancel_campaign(
    db: Session,
    *,
    campaign_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> PushNotificationCampaign:
    """Stop a campaign that has not gone out.

    A SENDING campaign is deliberately not cancellable here. Once dispatch has
    started, some customers already have the notification on their phone, and
    a status that claimed otherwise would be a lie about what happened.
    """

    campaign = get_campaign(db, campaign_id=campaign_id, restaurant_id=restaurant_id)
    _assert_transition(campaign, Status.CANCELLED)

    campaign.status = Status.CANCELLED
    campaign.scheduled_for = None
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    logger.info("Marketing campaign cancelled id=%s", campaign_id)
    return campaign


def schedule_campaign(
    db: Session,
    *,
    campaign_id: uuid.UUID,
    restaurant_id: uuid.UUID,
    send_at: datetime,
    now: datetime | None = None,
) -> PushNotificationCampaign:
    """Put a campaign in the queue for a future time.

    The time itself is validated here only for being in the future. Quiet
    hours, audience size and reachability are checked by `reach.estimate_reach`
    at the route, and again when the scheduled send actually fires — a campaign
    scheduled for Friday must be re-checked on Friday, not trusted from
    Tuesday.
    """

    now = now or datetime.now(UTC)
    campaign = get_campaign(db, campaign_id=campaign_id, restaurant_id=restaurant_id)
    _assert_transition(campaign, Status.SCHEDULED)

    if send_at <= now:
        raise CampaignValidationError(
            "That time has already passed. Choose a future time, or send now instead."
        )

    campaign.status = Status.SCHEDULED
    campaign.delivery_type = PushNotificationDeliveryType.SCHEDULED
    campaign.scheduled_for = send_at
    campaign.last_error = None
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    logger.info("Marketing campaign scheduled id=%s send_at=%s", campaign_id, send_at)
    return campaign


# --- sending ---------------------------------------------------------------


def claim_for_sending(
    db: Session,
    *,
    campaign_id: uuid.UUID,
    restaurant_id: uuid.UUID,
) -> PushNotificationCampaign:
    """Move a campaign to SENDING, or refuse.

    The claim is the concurrency control for the whole send path. Two workers
    can pick up the same due campaign — beat fires on an interval and a retried
    task is a second caller — and the row is what decides which of them owns
    it: the transition out of DRAFT/SCHEDULED happens once, and the second
    caller finds a SENDING campaign and is told it cannot send it again.

    Deliberately separate from `dispatch_campaign`: claiming is a short write
    that must commit immediately, while dispatch is a long loop that talks to
    Firebase. Doing both in one transaction would hold the row for the length
    of the send.
    """

    campaign = get_campaign(db, campaign_id=campaign_id, restaurant_id=restaurant_id)
    _assert_transition(campaign, Status.SENDING)

    if not campaign.title or not campaign.message:
        raise CampaignValidationError(
            "Write the message before sending it."
        )
    if not campaign.segment_key:
        raise CampaignValidationError(
            "Choose who this campaign is for before sending it."
        )

    campaign.status = Status.SENDING
    campaign.delivery_type = PushNotificationDeliveryType.INSTANT
    campaign.scheduled_for = None
    campaign.sending_progress = None
    campaign.last_error = None
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    logger.info("Marketing campaign claimed for sending id=%s", campaign_id)
    return campaign


def mark_send_failed(
    db: Session,
    *,
    campaign: PushNotificationCampaign,
    reason: str,
) -> PushNotificationCampaign:
    """Put a claimed campaign back down when the send could not start.

    Without this a campaign that failed before dispatch began would sit in
    SENDING forever: SENDING only leads to SENT or FAILED, so nothing else can
    move it and the owner cannot retry.
    """

    # The caller is usually handling an exception, and a failed flush leaves
    # the session unusable — without this rollback the write below raises
    # PendingRollbackError and the campaign is stranded in SENDING, which has
    # no way out except SENT or FAILED.
    db.rollback()
    campaign = db.merge(campaign)
    campaign.status = Status.FAILED
    campaign.sending_progress = None
    campaign.last_error = reason[:2000]
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    logger.warning("Marketing campaign send failed id=%s reason=%s", campaign.id, reason)
    return campaign


def due_scheduled_campaigns(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = 50,
) -> list[PushNotificationCampaign]:
    """Scheduled campaigns whose time has come, across every tenant.

    Read without a restaurant filter on purpose — this is the platform's
    scheduler, not a tenant request — which is why it lives here beside the
    lifecycle rules rather than in the route layer that enforces scoping.
    """

    now = now or datetime.now(UTC)
    return list(
        db.scalars(
            select(PushNotificationCampaign)
            .where(
                PushNotificationCampaign.kind == PushNotificationCampaignKind.MARKETING,
                PushNotificationCampaign.status == Status.SCHEDULED,
                PushNotificationCampaign.scheduled_for.is_not(None),
                PushNotificationCampaign.scheduled_for <= now,
            )
            .order_by(PushNotificationCampaign.scheduled_for.asc())
            .limit(limit)
        ).all()
    )


# --- presentation ----------------------------------------------------------


def _attribution_for(db: Session, campaign: PushNotificationCampaign) -> dict | None:
    """Recipient rows for a sent message, a promo code for a published post."""

    channel = _channel_of(campaign)
    if channel_family(channel) is MarketingChannelFamily.SOCIAL:
        return attribution_view(build_social_attribution(db, campaign))
    return attribution_view(build_attribution(db, campaign))


def _channel_of(campaign: PushNotificationCampaign) -> MarketingChannel:
    """The campaign's one channel, tolerant of a value this build lost.

    Falls back to push rather than raising: a report must still render for a
    campaign naming a channel that has since been removed, and push is the
    only behaviour that certainly exists.
    """

    for value in campaign.channels or []:
        try:
            return MarketingChannel(value)
        except ValueError:
            continue
    return MarketingChannel.PUSH


def campaign_view(
    campaign: PushNotificationCampaign,
    *,
    db: Session | None = None,
) -> dict:
    """A campaign row in the shape `types.ts` declares.

    Delivery is None until something was actually sent. The UI drives its empty
    state off that null, so returning a row of zeros for a draft would render a
    report about a campaign that never went out.

    `db` is optional because the list view renders dozens of rows and
    attribution is two queries per campaign. Pass it for the detail view, where
    the report is the point of the screen; omit it for a list, where the rows
    carry their delivery counters and nothing else.
    """

    has_sent = campaign.status in {Status.SENT, Status.SENDING} or campaign.sent_count > 0

    return {
        "id": campaign.id,
        "name": campaign.name or "Untitled campaign",
        "goal": MarketingCampaignGoal(campaign.goal or MarketingCampaignGoal.CUSTOM.value),
        "segment_key": MarketingSegmentKey(
            campaign.segment_key or MarketingSegmentKey.BRANCH_CUSTOMERS.value
        ),
        "branch_ids": [uuid.UUID(value) for value in (campaign.branch_ids or [])],
        "offer_id": campaign.offer_id,
        "channels": [MarketingChannel(value) for value in (campaign.channels or [])],
        "content": {
            "title": campaign.title,
            "body": campaign.message,
            "deep_link": MarketingDeepLink(
                campaign.deep_link or MarketingDeepLink.RESTAURANT_HOME.value
            ),
            "template_id": campaign.template_key,
            "extra": (campaign.data_payload or {}).get("content_extra") or {},
        },
        "schedule": {
            "mode": (
                "SCHEDULED"
                if campaign.delivery_type == PushNotificationDeliveryType.SCHEDULED
                else "NOW"
            ),
            "send_at": campaign.scheduled_for,
            "timezone": campaign.timezone,
        },
        "status": campaign.status,
        "created_at": campaign.created_at,
        "updated_at": campaign.updated_at,
        "sent_at": campaign.dispatched_at,
        "created_by": (
            campaign.created_by_user.full_name if campaign.created_by_user else "Unknown"
        ),
        "audience_size": campaign.estimated_recipient_count or 0,
        "delivery": (
            {
                "sent": campaign.sent_count or 0,
                "delivered": campaign.delivered_count or 0,
                "opened": campaign.opened_count or 0,
                "clicked": campaign.clicked_count or 0,
                "failed": campaign.failed_count or 0,
                "unsubscribed": campaign.unsubscribed_count or 0,
            }
            if has_sent
            else None
        ),
        # Both read from the recipient rows the dispatcher wrote. Without a
        # session they stay empty, which is what a list view asks for.
        "failure_reasons": (
            failure_reason_view(db, campaign) if db is not None and has_sent else []
        ),
        # Two different rules, chosen by what the campaign actually was. A
        # public post has no recipient rows to read, so its credit comes from
        # the promo code instead — see `attribution.py`, which says plainly
        # how much weaker that claim is.
        "attribution": (
            _attribution_for(db, campaign) if db is not None else None
        ),
        "social": social_post_view(campaign),
        "last_error": campaign.last_error,
        "sending_progress": (
            float(campaign.sending_progress)
            if campaign.sending_progress is not None
            else None
        ),
    }


def count_campaigns(db: Session, *, restaurant_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(PushNotificationCampaign)
            .where(*_marketing_scope(restaurant_id))
        )
        or 0
    )
