"""Sending a campaign, and recording who it went to.

This is the one path in the product that reaches a customer's lock screen
unprompted and cannot be recalled, so three things are true of it by design.

**The audience is recomputed here, never trusted from the draft.** A campaign
scheduled on Tuesday for Friday is sent to Friday's segment. Customers opt out,
uninstall, or stop qualifying in between, and sending to a list computed three
days ago would message people who have since said no.

**Firebase is only called when `enable_marketing_dispatch` is on.** With it off
the whole path still runs against the real audience and writes real recipient
rows — the owner can see exactly who a send would have reached — and no
external service is touched. A dry run that skipped the work would prove
nothing; one that lies about having sent is worse.

**A recipient is a row, not a counter.** `push_notification_campaign_recipients`
is what makes attribution answerable later, makes a half-failed send retryable
without double-messaging, and lets the report say *why* three people missed it.

The transactional order-push path in `services/notifications.py` is deliberately
untouched. It shares the Firebase app and the token-invalidation rule and
nothing else: its failure modes (404 on an empty audience, HTTPException from
deep inside a dispatch) are wrong for a background campaign send, and bending
it to serve both would have put the order notification at risk.

**This module no longer knows how any channel delivers.** It owns what is true
of every send — recompute the audience, write a row per customer, group by
rendered copy, commit progress per batch, decide the terminal status — and
asks `providers.provider_for` for something that can actually deliver. Adding
a channel is a provider plus a row in that factory, not an edit here.

**Social campaigns take a different path entirely, not a different branch at
the end.** A public post has no audience to recompute, no consent to check, no
recipient row to write and no frequency cap to apply. Running it through the
direct path with the people-shaped parts skipped would leave a campaign with
an audience of zero reported as a failed send. `publish_campaign` is therefore
a separate function, and `dispatch_campaign` routes to it on the channel's
family before any of the audience work happens.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    CampaignPostState,
    CampaignRecipientState,
    MarketingChannel,
    MarketingChannelFamily,
    MarketingSegmentKey,
    PushNotificationCampaignStatus,
    channel_family,
)
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.push_notification_campaign_recipient import (
    PushNotificationCampaignRecipient,
)
from app.models.user import User
from app.models.user_device_token import UserDeviceToken
from app.services.marketing.connections import get_connection, record_failure
from app.services.marketing.providers import (
    BatchMember,
    ProviderError,
    RenderedMessage,
    SocialContent,
    provider_for,
)
from app.services.marketing.providers.sms import parts as sms_parts
from app.services.marketing.reach import estimate_reach
from app.services.marketing.segments import (
    SegmentUnavailable,
    resolve_marketing_app_client_id,
)
from app.services.marketing.unsubscribe import unsubscribe_url

logger = logging.getLogger(__name__)
settings = get_settings()

Status = PushNotificationCampaignStatus


#: Merge fields and what they fall back to.
#:
#: The fallbacks are the same strings `frontend-admin`'s `mergeFields.ts` uses,
#: because the preview an owner approved has to be the message that goes out.
#: "there" rather than "customer": it reads as a greeting instead of a database
#: row, and it works in both "Hi {first_name}" and "We miss you, {first_name}".
MERGE_FALLBACKS = {
    "first_name": "there",
    "branch": "our kitchen",
}


class DispatchError(Exception):
    """A campaign could not be sent, with an owner-readable reason."""


@dataclass(slots=True)
class DispatchResult:
    campaign_id: uuid.UUID
    status: Status
    #: Customers the send was attempted for — the audience, not the token count.
    audience: int
    sent: int
    failed: int
    #: Reachable customers with no usable address on this channel. Not a
    #: failure: nothing was attempted and nothing went wrong.
    skipped: int
    dry_run: bool
    failure_reasons: dict[str, int] = field(default_factory=dict)
    #: Which channel actually ran, so a caller does not have to re-read the
    #: campaign to find out what it just did.
    channel: MarketingChannel = MarketingChannel.PUSH
    #: The public post, for a social campaign. None for every direct one —
    #: and the two are never both set, because a campaign is one or the other.
    post: dict | None = None


def render_merge_fields(text: str, *, first_name: str | None, branch: str | None) -> str:
    """Resolve `{first_name}` and `{branch}`, never leaving a raw token behind.

    A customer with no first name on file is the case this exists for: sending
    "Hi {first_name}" or, worse, "Hi None" to a real person is the single most
    embarrassing thing a campaign can do.
    """

    resolved_name = (first_name or "").strip() or MERGE_FALLBACKS["first_name"]
    resolved_branch = (branch or "").strip() or MERGE_FALLBACKS["branch"]
    return text.replace("{first_name}", resolved_name).replace("{branch}", resolved_branch)


def _first_name(full_name: str | None) -> str | None:
    if not full_name:
        return None
    return full_name.strip().split(" ")[0] or None



def campaign_channel(campaign: PushNotificationCampaign) -> MarketingChannel:
    """The one channel this campaign runs on.

    The column is still a list because that is what the schema and the wire
    have always carried, but a campaign names exactly one channel and every
    read goes through here. An empty list is a campaign written before the
    Hub stored channels at all, and push is what those were.
    """

    values = campaign.channels or []
    if not values:
        return MarketingChannel.PUSH
    try:
        return MarketingChannel(values[0])
    except ValueError as exc:
        raise DispatchError(
            f"This campaign names a channel this system does not know: {values[0]}."
        ) from exc


def _message_parts(campaign: PushNotificationCampaign, channel: MarketingChannel) -> int:
    """How many billable messages one copy of this is.

    Only SMS charges by length. Asking here rather than inside the cost
    calculation keeps the quote the owner saw and the bill they receive
    derived from the same function.
    """

    if channel is MarketingChannel.SMS:
        return sms_parts(campaign.message or "")
    return 1


def _recompute_audience(
    db: Session,
    campaign: PushNotificationCampaign,
    *,
    channel: MarketingChannel,
) -> list[uuid.UUID]:
    """The customers this campaign goes to, as of now.

    Raises `DispatchError` for anything that makes sending wrong rather than
    merely empty — a blocked reach result carries the owner-readable reason
    the reach step would have shown.
    """

    if campaign.restaurant_id is None:
        raise DispatchError("This campaign is not attached to a restaurant.")
    if not campaign.segment_key:
        raise DispatchError("Choose who this campaign is for before sending it.")
    if not campaign.title or not campaign.message:
        raise DispatchError("Write the message before sending it.")

    try:
        app_client_id = resolve_marketing_app_client_id(db, campaign.restaurant_id)
    except SegmentUnavailable as exc:
        raise DispatchError(str(exc)) from exc

    branch_ids = [uuid.UUID(str(value)) for value in (campaign.branch_ids or [])]

    result = estimate_reach(
        db,
        restaurant_id=campaign.restaurant_id,
        app_client_id=app_client_id,
        segment_key=MarketingSegmentKey(campaign.segment_key),
        branch_ids=branch_ids,
        # Exactly this campaign's channel, never a list: `reachable_user_ids`
        # is whichever direct channel was evaluated last, so passing two would
        # send this campaign to the other one's audience.
        channels=[channel],
        # Now, not the scheduled time: this IS the send, and quiet hours apply
        # to when the phone actually buzzes.
        send_at=None,
        message_parts=_message_parts(campaign, channel),
    )
    if result.blocked():
        raise DispatchError(result.blocking_reason() or "This campaign cannot be sent yet.")
    return list(result.reachable_user_ids)


def _tokens_by_user(
    db: Session, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[UserDeviceToken]]:
    if not user_ids:
        return {}
    rows = db.scalars(
        select(UserDeviceToken).where(
            UserDeviceToken.user_id.in_(user_ids),
            UserDeviceToken.is_active.is_(True),
        )
    ).all()
    grouped: dict[uuid.UUID, list[UserDeviceToken]] = {}
    for row in rows:
        grouped.setdefault(row.user_id, []).append(row)
    return grouped


def _load_recipients(
    db: Session, campaign_id: uuid.UUID
) -> dict[uuid.UUID, PushNotificationCampaignRecipient]:
    """Every recipient row this campaign already has, keyed by customer.

    One query rather than one per customer: an audience of ten thousand would
    otherwise open the send with ten thousand round trips before a single
    notification left the building.

    Rows exist here only when a previous attempt wrote them, which is what
    makes a retry skip the people it already reached.
    """

    return {
        row.user_id: row
        for row in db.scalars(
            select(PushNotificationCampaignRecipient).where(
                PushNotificationCampaignRecipient.campaign_id == campaign_id
            )
        ).all()
    }


def _recipient_for(
    db: Session,
    recipients: dict[uuid.UUID, PushNotificationCampaignRecipient],
    campaign_id: uuid.UUID,
    user_id: uuid.UUID,
) -> PushNotificationCampaignRecipient:
    """This customer's row, created once and then reused.

    The map is the point. Re-querying here instead would miss rows added to the
    session but not yet flushed, and insert a second row for the same customer
    — which the unique constraint then refuses, failing the whole send.
    """

    existing = recipients.get(user_id)
    if existing is not None:
        return existing
    recipient = PushNotificationCampaignRecipient(
        campaign_id=campaign_id,
        user_id=user_id,
        state=CampaignRecipientState.PENDING,
    )
    db.add(recipient)
    recipients[user_id] = recipient
    return recipient



def _addresses_by_user(
    db: Session,
    *,
    provider,
    channel: MarketingChannel,
    user_ids: list[uuid.UUID],
    users: dict[uuid.UUID, User],
) -> dict[uuid.UUID, list[str]]:
    """Where each customer can be reached on this channel.

    Push is the one channel whose address is not on the user row — a customer
    has many device tokens, in another table — so it is fetched in bulk here
    rather than asked of the provider per user. Everything else reads a
    column, and `provider.addresses_for` is what knows which column and in
    what shape (Meta wants a phone number with no `+`; the kitchen prints one
    with).
    """

    if channel is MarketingChannel.PUSH:
        grouped = _tokens_by_user(db, user_ids)
        return {
            user_id: list(dict.fromkeys(token.fcm_token for token in tokens))
            for user_id, tokens in grouped.items()
        }
    return {
        user_id: provider.addresses_for(users[user_id])
        for user_id in user_ids
        if user_id in users
    }


def _campaign_extra(campaign: PushNotificationCampaign) -> dict:
    """The per-channel content bag, as the editor filled it in."""

    return dict((campaign.data_payload or {}).get("content_extra") or {})


def dispatch_campaign(
    db: Session,
    *,
    campaign: PushNotificationCampaign,
    now: datetime | None = None,
) -> DispatchResult:
    """Send or publish a campaign, whichever its channel means.

    The campaign is already SENDING when this is called — the caller claims it
    under a transaction so two workers cannot send the same campaign twice.
    This function owns everything after that claim, including deciding the
    terminal status.
    """

    channel = campaign_channel(campaign)
    if channel_family(channel) is MarketingChannelFamily.SOCIAL:
        return publish_campaign(db, campaign=campaign, channel=channel, now=now)
    return _dispatch_direct(db, campaign=campaign, channel=channel, now=now)


def _dispatch_direct(
    db: Session,
    *,
    campaign: PushNotificationCampaign,
    channel: MarketingChannel,
    now: datetime | None = None,
) -> DispatchResult:
    """Send to named people, recording a row per customer as it goes.

    Progress is committed per batch rather than at the end, because a SENDING
    campaign is something the owner is watching: a bar that only moves when
    the send finishes is not progress, it is a spinner.
    """

    now = now or datetime.now(UTC)
    dry_run = not settings.enable_marketing_dispatch

    audience = _recompute_audience(db, campaign, channel=channel)
    if not audience:
        # Not an error state. The segment emptied between scheduling and now,
        # which is a real answer the owner needs to see rather than a failure
        # to retry — nobody qualifies today.
        campaign.status = Status.SENT
        campaign.sent_count = 0
        campaign.delivered_count = 0
        campaign.failed_count = 0
        campaign.sending_progress = None
        campaign.dispatched_at = now
        campaign.last_error = "Nobody matched this audience at send time."
        db.add(campaign)
        db.commit()
        logger.info("Marketing campaign had an empty audience id=%s", campaign.id)
        return DispatchResult(
            campaign_id=campaign.id,
            status=Status.SENT,
            audience=0,
            sent=0,
            failed=0,
            skipped=0,
            dry_run=dry_run,
            channel=channel,
        )

    # Built even on a dry run. Constructing the provider is what proves the
    # channel is connected and configured, and an owner inspecting a dry run
    # should learn that their WhatsApp token is missing — not discover it the
    # first time they send for real.
    connection = get_connection(
        db, restaurant_id=campaign.restaurant_id, channel=channel
    )
    try:
        provider = provider_for(channel, connection)
    except ProviderError as exc:
        raise DispatchError(str(exc)) from exc

    users = {
        row.id: row
        for row in db.scalars(select(User).where(User.id.in_(audience))).all()
    }
    addresses = _addresses_by_user(
        db, provider=provider, channel=channel, user_ids=audience, users=users
    )
    branch_name = _primary_branch_name(db, campaign)
    extra = _campaign_extra(campaign)

    data = {
        "notification_type": "marketing",
        "category": (campaign.goal or "MARKETING"),
        "audience": campaign.audience.value,
        "notification_id": str(campaign.id),
        "campaign_id": str(campaign.id),
        "deep_link": campaign.deep_link or "",
        "order_id": "",
    }

    batch_size = max(1, min(provider.max_batch(), settings.marketing_dispatch_batch_size))

    sent = 0
    failed = 0
    skipped = 0
    reasons: dict[str, int] = {}
    dead_addresses: set[str] = set()

    # Grouped by rendered copy so customers who resolve to the same message
    # share one call. Personalised copy costs one batch per distinct text,
    # which is the price of merge fields and is bounded by the audience.
    recipients = _load_recipients(db, campaign.id)
    pending: dict[tuple[str, str], list[BatchMember]] = {}
    for user_id in audience:
        recipient = _recipient_for(db, recipients, campaign.id, user_id)
        if recipient.state is CampaignRecipientState.SENT:
            # Already reached by an earlier attempt at this same campaign.
            sent += 1
            continue

        member_addresses = addresses.get(user_id) or []
        recipient.device_token_count = len(member_addresses)
        if not member_addresses:
            recipient.state = CampaignRecipientState.SKIPPED
            recipient.failure_reason = _no_address_reason(channel)
            skipped += 1
            continue

        user = users.get(user_id)
        first_name = _first_name(user.full_name if user else None)
        key = (
            render_merge_fields(campaign.title, first_name=first_name, branch=branch_name),
            render_merge_fields(campaign.message, first_name=first_name, branch=branch_name),
        )
        pending.setdefault(key, []).append(
            BatchMember(user_id=user_id, addresses=member_addresses)
        )

    total = len(audience)
    processed = sent + skipped

    for (title, body), members in pending.items():
        for start in range(0, len(members), batch_size):
            window = members[start : start + batch_size]
            message = RenderedMessage(
                title=title,
                body=body,
                data=data,
                # Per batch, because the unsubscribe link is per recipient and
                # only this window's recipients are in scope.
                extra={**extra, **_per_recipient_extra(channel, campaign, window)},
            )

            outcomes = _deliver(
                provider=provider,
                members=window,
                message=message,
                dry_run=dry_run,
                campaign_id=campaign.id,
            )

            for outcome in outcomes:
                recipient = _recipient_for(db, recipients, campaign.id, outcome.user_id)
                if outcome.delivered:
                    recipient.state = CampaignRecipientState.SENT
                    recipient.sent_at = datetime.now(UTC)
                    recipient.failure_reason = None
                    sent += 1
                else:
                    recipient.state = CampaignRecipientState.FAILED
                    reason = outcome.reason or "Delivery failed"
                    recipient.failure_reason = reason[:255]
                    reasons[reason] = reasons.get(reason, 0) + 1
                    failed += 1
                dead_addresses |= set(outcome.dead_addresses)

            processed += len(window)
            campaign.sending_progress = _progress(processed, total)
            campaign.sent_count = sent
            campaign.delivered_count = sent
            campaign.failed_count = failed
            db.add(campaign)
            db.commit()

    if dead_addresses and channel is MarketingChannel.PUSH:
        # A token Firebase rejected as unregistered is an app that is gone.
        # Leaving it active would make every future campaign report the same
        # failure forever.
        #
        # Only push: a bounced email and an unreachable phone number live on
        # the user row, and blanking a customer's phone number because one
        # gateway refused it once would cost the restaurant a delivery
        # address. The failure is recorded on the recipient row instead.
        for token_row in db.scalars(
            select(UserDeviceToken).where(UserDeviceToken.fcm_token.in_(dead_addresses))
        ).all():
            token_row.is_active = False
            db.add(token_row)

    campaign.status = Status.SENT if sent > 0 or skipped == total else Status.FAILED
    campaign.sent_count = sent
    campaign.delivered_count = sent
    campaign.failed_count = failed
    campaign.sending_progress = None
    campaign.dispatched_at = datetime.now(UTC)
    campaign.last_error = _summarize(reasons) if reasons else None
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    if campaign.status is Status.FAILED and campaign.restaurant_id and not dry_run:
        # The picker should say the channel is in trouble, not leave the owner
        # to infer it from a failed campaign.
        record_failure(
            db,
            restaurant_id=campaign.restaurant_id,
            channel=channel,
            reason=campaign.last_error or "The last send failed.",
        )

    logger.info(
        "Marketing campaign dispatched id=%s channel=%s audience=%s sent=%s failed=%s skipped=%s dry_run=%s",
        campaign.id,
        channel.value,
        total,
        sent,
        failed,
        skipped,
        dry_run,
    )
    return DispatchResult(
        campaign_id=campaign.id,
        status=campaign.status,
        audience=total,
        sent=sent,
        failed=failed,
        skipped=skipped,
        dry_run=dry_run,
        failure_reasons=reasons,
        channel=channel,
    )


def _deliver(*, provider, members, message, dry_run: bool, campaign_id: uuid.UUID):
    """One batch, with a provider failure turned into per-recipient outcomes.

    A `ProviderError` from `send` means the whole batch failed — a refused
    token, an unreachable gateway. It is caught rather than raised so the
    remaining batches still go: the campaign is already SENDING and the other
    nine hundred people are still owed their message. The reason lands on each
    of this batch's recipient rows, which is where the report reads it from.
    """

    from app.services.marketing.providers.base import MemberOutcome

    if dry_run:
        # Everything up to the wire actually ran: the audience is real, the
        # recipient rows are real, the provider was constructed and its
        # configuration validated. Only the call is skipped.
        return [MemberOutcome(user_id=member.user_id, delivered=True) for member in members]

    try:
        return provider.send(members, message=message).outcomes
    except ProviderError as exc:
        logger.warning("Marketing batch refused campaign_id=%s: %s", campaign_id, exc)
        return [
            MemberOutcome(user_id=member.user_id, delivered=False, reason=str(exc))
            for member in members
        ]
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        logger.exception("Marketing batch crashed campaign_id=%s", campaign_id)
        return [
            MemberOutcome(user_id=member.user_id, delivered=False, reason=str(exc))
            for member in members
        ]


def _no_address_reason(channel: MarketingChannel) -> str:
    """Why this customer was skipped, in the words of the channel.

    "No active device" is right for push and meaningless for email. The
    reason is shown verbatim in the campaign report, so it has to name the
    thing the owner would have to collect.
    """

    return {
        MarketingChannel.PUSH: "No active device",
        MarketingChannel.SMS: "No mobile number on file",
        MarketingChannel.WHATSAPP: "No mobile number on file",
        MarketingChannel.EMAIL: "No email address on file",
    }.get(channel, "No way to reach this customer")


def _per_recipient_extra(
    channel: MarketingChannel,
    campaign: PushNotificationCampaign,
    members: list[BatchMember],
) -> dict:
    """Anything the provider needs that differs per person in the batch.

    Only email so far: every message must carry an unsubscribe link, and the
    link names the recipient. Built from the HMAC token the hosted opt-out
    page already verifies — the one P1 built for exactly this and said would
    be reused here.
    """

    if channel is not MarketingChannel.EMAIL:
        return {}
    urls = {}
    for member in members:
        url = unsubscribe_url(member.user_id, campaign.id)
        if url:
            urls[str(member.user_id)] = url
    return {"unsubscribe_urls": urls}


def publish_campaign(
    db: Session,
    *,
    campaign: PushNotificationCampaign,
    channel: MarketingChannel,
    now: datetime | None = None,
) -> DispatchResult:
    """Put one public post up, and record where it went.

    Nothing here resembles the direct path, which is the whole reason it is a
    separate function. There is no audience to recompute, no consent to check,
    no recipient row to write and no frequency cap: a post is seen by whoever
    the platform shows it to, and this product has no identity for those
    people.

    What it records instead is the post itself — the platform's id and a
    permalink — because that is the only handle the report has. Attribution
    reads a promo code from orders, not recipient rows, and the campaign's
    delivery counters stay at zero on purpose: they count people reached, and
    reporting `sent: 1` for a post would put a post and a person in the same
    column.
    """

    now = now or datetime.now(UTC)
    dry_run = not settings.enable_marketing_dispatch

    if campaign.restaurant_id is None:
        raise DispatchError("This campaign is not attached to a restaurant.")
    if not campaign.message:
        raise DispatchError("Write the post before publishing it.")

    extra = _campaign_extra(campaign)
    connection = get_connection(
        db, restaurant_id=campaign.restaurant_id, channel=channel
    )
    try:
        provider = provider_for(channel, connection)
    except ProviderError as exc:
        raise DispatchError(str(exc)) from exc

    content = SocialContent(
        caption=campaign.message,
        image_url=extra.get("image_url") or campaign.image_url,
        link_url=extra.get("link_url"),
        cta_label=extra.get("cta_label"),
        hashtags=extra.get("hashtags"),
        hashtags_in_comment=bool(extra.get("hashtags_in_comment")),
    )

    if dry_run:
        post = {
            "state": CampaignPostState.PUBLISHED.value,
            "post_id": None,
            "permalink": None,
            "published_at": now.isoformat(),
            # Said in the record rather than inferred from a null post id, so
            # the report can state plainly that nothing was posted.
            "dry_run": True,
        }
        error = None
    else:
        try:
            result = provider.publish(content)
        except ProviderError as exc:
            _record_post(db, campaign, {
                "state": CampaignPostState.FAILED.value,
                "reason": str(exc)[:500],
                "attempted_at": now.isoformat(),
            })
            record_failure(
                db,
                restaurant_id=campaign.restaurant_id,
                channel=channel,
                reason=str(exc),
            )
            raise DispatchError(str(exc)) from exc
        post = {
            "state": CampaignPostState.PUBLISHED.value,
            "post_id": result.post_id,
            "permalink": result.permalink,
            "published_at": now.isoformat(),
            "dry_run": False,
        }
        error = None

    _record_post(db, campaign, post)

    campaign.status = Status.SENT
    campaign.sending_progress = None
    campaign.dispatched_at = now
    campaign.last_error = (
        "Sending is switched off in this environment, so nothing was posted."
        if dry_run
        else error
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    logger.info(
        "Marketing campaign published id=%s channel=%s post_id=%s dry_run=%s",
        campaign.id,
        channel.value,
        post.get("post_id"),
        dry_run,
    )
    return DispatchResult(
        campaign_id=campaign.id,
        status=campaign.status,
        audience=0,
        sent=0,
        failed=0,
        skipped=0,
        dry_run=dry_run,
        channel=channel,
        post=post,
    )


def _record_post(db: Session, campaign: PushNotificationCampaign, post: dict) -> None:
    """Keep the post record beside the content it came from.

    Namespaced under its own key in `data_payload` for the same reason
    `content_extra` is: the column is shared with the transactional push path
    and must be merged into, never assigned over.
    """

    campaign.data_payload = {**(campaign.data_payload or {}), "social_post": post}
    db.add(campaign)
    db.commit()


def _progress(processed: int, total: int) -> Decimal | None:
    if total <= 0:
        return None
    return Decimal(min(processed, total)) / Decimal(total)


def _summarize(reasons: dict[str, int]) -> str:
    """The three commonest failures, for a message an owner reads."""

    ranked = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[:3]
    return ", ".join(f"{reason} ({count})" for reason, count in ranked)[:2000]


def _primary_branch_name(db: Session, campaign: PushNotificationCampaign) -> str | None:
    """The branch `{branch}` resolves to.

    One name for the whole send, even when several branches were selected: the
    alternative is telling a customer about a branch they did not order from,
    and the fallback ("our kitchen") is written to read correctly either way.
    """

    from app.models.restaurant_location import RestaurantLocation

    branch_ids = [uuid.UUID(str(value)) for value in (campaign.branch_ids or [])]
    if len(branch_ids) != 1:
        return None
    location = db.get(RestaurantLocation, branch_ids[0])
    return location.branch_name if location is not None else None
