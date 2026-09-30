"""Campaign sending, off the request thread.

A send talks to Firebase once per batch against an audience that can be
thousands of customers. Doing that inside the HTTP request would hold the
owner's browser open for the length of it and lose the send entirely if they
navigated away, so the route claims the campaign and hands the work here.

Two entry points, one path: `send_marketing_campaign_task` is the owner
pressing Send, `run_due_marketing_campaigns_task` is beat finding campaigns
whose scheduled time has arrived. Both end in `dispatch_campaign`, which is
what keeps a scheduled send and an immediate one from drifting apart — and
which now routes a social campaign to `publish_campaign` instead, so the same
two entry points cover posting as well as sending.

A third task, `refresh_social_insights_task`, pulls a published post's numbers
back from Meta. It exists because a post has no delivery callback: a push
reports per recipient as it goes, and an Instagram post just sits there
accumulating impressions that nothing tells us about. Polled rather than
subscribed because the webhook for it requires an app review this product has
not been through, and a number that is an hour stale is much better than no
number at all.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.models.enums import PushNotificationCampaignStatus
from app.models.push_notification_campaign import PushNotificationCampaign
from app.services.marketing import campaigns as campaign_service
from app.services.marketing.dispatch import DispatchError, dispatch_campaign

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.marketing.send_marketing_campaign")
def send_marketing_campaign_task(campaign_id: str) -> dict[str, Any]:
    """Dispatch one campaign that has already been claimed as SENDING.

    Not retried automatically. A partially-sent campaign that retried on its
    own would re-enter dispatch while the owner was reading a half-finished
    report, and the recipient rows — not a retry policy — are what make a
    second attempt safe. Retrying is therefore the owner's decision, from a
    FAILED campaign they can see.
    """

    with SessionLocal() as db:
        campaign = db.get(PushNotificationCampaign, uuid.UUID(campaign_id))
        if campaign is None:
            logger.warning("Marketing send skipped, campaign gone id=%s", campaign_id)
            return {"campaign_id": campaign_id, "status": "missing"}
        if campaign.status is not PushNotificationCampaignStatus.SENDING:
            # Someone else already took it, or it was cancelled between the
            # claim and this worker picking the job up.
            logger.info(
                "Marketing send skipped, campaign is %s id=%s",
                campaign.status.value,
                campaign_id,
            )
            return {"campaign_id": campaign_id, "status": campaign.status.value}

        try:
            result = dispatch_campaign(db, campaign=campaign)
        except DispatchError as exc:
            campaign_service.mark_send_failed(db, campaign=campaign, reason=str(exc))
            return {"campaign_id": campaign_id, "status": "FAILED", "reason": str(exc)}
        except Exception as exc:  # noqa: BLE001 - recorded, so the owner can retry
            logger.exception("Marketing send crashed id=%s", campaign_id)
            campaign_service.mark_send_failed(
                db, campaign=campaign, reason=f"The send did not complete: {exc}"
            )
            raise

        return {
            "campaign_id": campaign_id,
            "status": result.status.value,
            "audience": result.audience,
            "sent": result.sent,
            "failed": result.failed,
            "skipped": result.skipped,
            "dry_run": result.dry_run,
        }


@celery_app.task(name="app.tasks.marketing.run_due_marketing_campaigns")
def run_due_marketing_campaigns_task() -> dict[str, Any]:
    """Send the campaigns whose scheduled time has passed.

    Each campaign is claimed individually and dispatched in the same worker
    rather than fanned out: the claim is what prevents a double send, and it is
    only meaningful if the claimer is the sender. A campaign that fails here
    does not stop the others — one tenant's broken segment must not hold up
    everybody else's Friday send.
    """

    started: list[str] = []
    with SessionLocal() as db:
        due = campaign_service.due_scheduled_campaigns(db)
        for campaign in due:
            if campaign.restaurant_id is None:
                continue
            try:
                claimed = campaign_service.claim_for_sending(
                    db,
                    campaign_id=campaign.id,
                    restaurant_id=campaign.restaurant_id,
                )
            except campaign_service.CampaignValidationError as exc:
                # Lost the race, or the campaign is no longer sendable. Either
                # way it is not this run's to send.
                logger.info("Scheduled campaign not claimable id=%s: %s", campaign.id, exc)
                continue

            started.append(str(claimed.id))
            try:
                dispatch_campaign(db, campaign=claimed)
            except DispatchError as exc:
                campaign_service.mark_send_failed(db, campaign=claimed, reason=str(exc))
            except Exception as exc:  # noqa: BLE001 - one tenant must not block the rest
                logger.exception("Scheduled send crashed id=%s", claimed.id)
                campaign_service.mark_send_failed(
                    db, campaign=claimed, reason=f"The send did not complete: {exc}"
                )

    if started:
        logger.info("Scheduled marketing campaigns dispatched count=%s", len(started))
    return {"dispatched": started}


@celery_app.task(name="app.tasks.marketing.refresh_social_insights")
def refresh_social_insights_task() -> dict[str, Any]:
    """Pull impressions and engagement back for recently published posts.

    Bounded two ways. Only campaigns published inside
    `marketing_social_insight_days` are refreshed — Meta's numbers keep
    moving for days and then stop, and polling a three-month-old post is pure
    cost. And a failure on one post is logged and skipped, because one
    restaurant's expired token must not stop everybody else's numbers
    updating.

    The fetched values are stored under their own key rather than merged into
    the campaign's counters. `sent_count` and the rest count people reached
    on a direct send; impressions are a different thing measured a different
    way, and adding them into the same column would make the Hub's headline
    revenue figures uncomparable between channels.
    """

    from datetime import UTC, datetime, timedelta

    from app.config import get_settings
    from app.models.enums import (
        MarketingChannel,
        MarketingChannelFamily,
        PushNotificationCampaignKind,
        channel_family,
    )
    from app.services.marketing.connections import get_connection
    from app.services.marketing.providers import ProviderError, provider_for

    settings = get_settings()
    if not settings.enable_marketing_dispatch:
        # Nothing was ever posted, so there is nothing to ask about. Polling
        # Meta for a post id that does not exist would fill the log with
        # errors describing a dry run working correctly.
        return {"refreshed": 0, "skipped": "dispatch disabled"}

    cutoff = datetime.now(UTC) - timedelta(days=settings.marketing_social_insight_days)
    refreshed = 0

    with SessionLocal() as db:
        candidates = db.scalars(
            select(PushNotificationCampaign).where(
                PushNotificationCampaign.kind == PushNotificationCampaignKind.MARKETING,
                PushNotificationCampaign.status
                == PushNotificationCampaignStatus.SENT,
                PushNotificationCampaign.dispatched_at.is_not(None),
                PushNotificationCampaign.dispatched_at >= cutoff,
            )
        ).all()

        for campaign in candidates:
            post = (campaign.data_payload or {}).get("social_post") or {}
            post_id = post.get("post_id")
            if not post_id or campaign.restaurant_id is None:
                continue
            try:
                channel = MarketingChannel((campaign.channels or [None])[0])
            except (ValueError, IndexError):
                continue
            if channel_family(channel) is not MarketingChannelFamily.SOCIAL:
                continue

            try:
                provider = provider_for(
                    channel,
                    get_connection(
                        db, restaurant_id=campaign.restaurant_id, channel=channel
                    ),
                )
                values = provider.insights(str(post_id))
            except ProviderError as exc:
                logger.info(
                    "Social insights unavailable campaign_id=%s: %s", campaign.id, exc
                )
                continue
            except Exception:  # noqa: BLE001 - one post must not stop the rest
                logger.exception("Social insights crashed campaign_id=%s", campaign.id)
                continue

            campaign.data_payload = {
                **(campaign.data_payload or {}),
                "social_insights": {
                    **values,
                    "fetched_at": datetime.now(UTC).isoformat(),
                },
            }
            db.add(campaign)
            db.commit()
            refreshed += 1

    if refreshed:
        logger.info("Social insights refreshed count=%s", refreshed)
    return {"refreshed": refreshed}
