"""Which channels a restaurant can actually send on, and what they need.

The Hub's channel picker asks one question of this module — *is this channel
live for this restaurant?* — and the send path asks the same question again
before it touches a provider. Both answers come from here so they cannot
disagree, which is the mistake the previous version made in miniature: a
hardcoded `PHASE_TWO_CHANNELS` map in `catalog.py` said WhatsApp was
unavailable, and nothing else in the system could have said otherwise even
once it was.

Three things this module is careful about.

**Absence of a row is the "not connected" state.** There is no NOT_CONNECTED
status to fall out of step with the row's existence.

**Push has no connection and never will.** Its credentials are the platform's
Firebase service account, shared by every restaurant. Giving it a row would
mean an owner could disconnect the channel their order notifications ride on.
`requirements_for` returns nothing for it and `is_live` is unconditionally
true.

**Credentials go in and never come out.** `connect` takes them, the model
stores them, and no function here returns them. `ConnectionView` is what the
API serialises, and it carries `config` plus a masked hint — enough for an
owner to see which number they are sending from, never enough to send from it
somewhere else.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    ChannelConnectionStatus,
    MarketingChannel,
    MarketingChannelFamily,
    channel_family,
)
from app.models.restaurant_channel_connection import RestaurantChannelConnection

logger = logging.getLogger(__name__)


class ConnectionError_(Exception):
    """A connection could not be saved, with an owner-readable reason."""


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One thing the owner has to supply to switch a channel on.

    `secret` decides which JSONB column it lands in, and therefore whether it
    is ever returned. `example` is shown as a placeholder rather than as help
    text — an owner recognises the shape of their own WhatsApp number faster
    than they read a sentence about it.
    """

    key: str
    label: str
    example: str
    secret: bool = False
    required: bool = True
    help: str = ""


#: What each channel needs before it can send, in the owner's words.
#:
#: These are the real fields of the real APIs — Meta's Cloud API wants a phone
#: number id and a permanent token, the Graph API wants a page or IG user id.
#: Naming them honestly is the difference between a form an owner can complete
#: by pasting from Meta's dashboard and one they have to guess at.
REQUIREMENTS: dict[MarketingChannel, tuple[FieldSpec, ...]] = {
    MarketingChannel.WHATSAPP: (
        FieldSpec(
            key="phone_number_id",
            label="WhatsApp phone number ID",
            example="109876543210987",
            help="From Meta Business → WhatsApp → API setup. Not the phone number itself.",
        ),
        FieldSpec(
            key="display_phone_number",
            label="The number customers will see",
            example="+91 80 4718 2203",
            required=False,
        ),
        FieldSpec(
            key="access_token",
            label="Permanent access token",
            example="EAAG…",
            secret=True,
            help="Meta Business → System users → Generate token. A temporary token expires in a day.",
        ),
    ),
    MarketingChannel.SMS: (
        FieldSpec(
            key="sender_id",
            label="Sender name",
            example="SPICER",
            help="The six letters your operator approved. Customers see this instead of a number.",
        ),
        FieldSpec(
            key="api_url",
            label="Your SMS provider's send URL",
            example="https://api.provider.com/v1/sms",
        ),
        FieldSpec(
            key="api_key",
            label="API key",
            example="sk_live_…",
            secret=True,
        ),
    ),
    MarketingChannel.EMAIL: (
        FieldSpec(
            key="from_email",
            label="Send from",
            example="hello@spiceroute.in",
            help="Has to be on a domain you have verified, or your mail lands in spam.",
        ),
        FieldSpec(key="from_name", label="Send as", example="Spice Route", required=False),
        FieldSpec(key="smtp_host", label="Mail server", example="smtp.provider.com"),
        FieldSpec(key="smtp_port", label="Port", example="587", required=False),
        FieldSpec(key="smtp_username", label="Username", example="apikey", required=False),
        FieldSpec(key="smtp_password", label="Password", example="", secret=True, required=False),
    ),
    MarketingChannel.INSTAGRAM: (
        FieldSpec(
            key="ig_user_id",
            label="Instagram account ID",
            example="17841400000000000",
            help="A business or creator account, linked to a Facebook Page.",
        ),
        FieldSpec(key="username", label="Handle", example="spiceroute", required=False),
        FieldSpec(
            key="follower_count",
            label="Followers",
            example="4200",
            required=False,
            help="Only used to show a rough number while building a post.",
        ),
        FieldSpec(key="access_token", label="Page access token", example="EAAG…", secret=True),
    ),
    MarketingChannel.FACEBOOK: (
        FieldSpec(key="page_id", label="Facebook Page ID", example="102938475601234"),
        FieldSpec(key="page_name", label="Page name", example="Spice Route", required=False),
        FieldSpec(
            key="follower_count", label="Followers", example="8100", required=False
        ),
        FieldSpec(key="access_token", label="Page access token", example="EAAG…", secret=True),
    ),
}


@dataclass(slots=True)
class ConnectionView:
    """A connection as the API returns it. Never carries a credential."""

    channel: MarketingChannel
    family: MarketingChannelFamily
    connected: bool
    status: ChannelConnectionStatus | None
    config: dict = field(default_factory=dict)
    #: "Sending as +91 80 4718 2203" — who the customer will see it from.
    identity: str | None = None
    connected_at: datetime | None = None
    verified_at: datetime | None = None
    last_error: str | None = None
    #: The fields this channel still needs, for the connect form.
    requirements: tuple[FieldSpec, ...] = ()


def requirements_for(channel: MarketingChannel) -> tuple[FieldSpec, ...]:
    return REQUIREMENTS.get(channel, ())


def get_connection(
    db: Session, *, restaurant_id: uuid.UUID, channel: MarketingChannel
) -> RestaurantChannelConnection | None:
    return db.scalars(
        select(RestaurantChannelConnection).where(
            RestaurantChannelConnection.restaurant_id == restaurant_id,
            RestaurantChannelConnection.channel == channel.value,
        )
    ).first()


def list_connections(
    db: Session, *, restaurant_id: uuid.UUID
) -> dict[MarketingChannel, RestaurantChannelConnection]:
    rows = db.scalars(
        select(RestaurantChannelConnection).where(
            RestaurantChannelConnection.restaurant_id == restaurant_id
        )
    ).all()
    out: dict[MarketingChannel, RestaurantChannelConnection] = {}
    for row in rows:
        try:
            out[MarketingChannel(row.channel)] = row
        except ValueError:
            # A channel this build no longer knows. Skipped rather than
            # raising: one stale row must not break the whole picker.
            logger.warning("Unknown channel on connection row id=%s: %s", row.id, row.channel)
    return out


def is_live(
    db: Session, *, restaurant_id: uuid.UUID, channel: MarketingChannel
) -> bool:
    """Whether a campaign on this channel may actually leave the building.

    Push is always live: it is the platform's own Firebase app, and the only
    switch over it is `enable_marketing_dispatch`, which is global and checked
    in dispatch rather than here.
    """

    if channel is MarketingChannel.PUSH:
        return True
    connection = get_connection(db, restaurant_id=restaurant_id, channel=channel)
    return connection is not None and connection.is_sendable()


def _identity(channel: MarketingChannel, config: dict) -> str | None:
    """Who the customer sees this coming from, in one line.

    Worth the per-channel branch: "connected" tells an owner nothing, and the
    question they actually have before pressing send is *from which of my
    numbers*.
    """

    if channel is MarketingChannel.WHATSAPP:
        return config.get("display_phone_number") or config.get("phone_number_id")
    if channel is MarketingChannel.SMS:
        return config.get("sender_id")
    if channel is MarketingChannel.EMAIL:
        name, address = config.get("from_name"), config.get("from_email")
        return f"{name} <{address}>" if name and address else address
    if channel is MarketingChannel.INSTAGRAM:
        handle = config.get("username")
        return f"@{handle}" if handle else config.get("ig_user_id")
    if channel is MarketingChannel.FACEBOOK:
        return config.get("page_name") or config.get("page_id")
    return None


def view_for(
    channel: MarketingChannel, connection: RestaurantChannelConnection | None
) -> ConnectionView:
    """One channel's state, as the picker and the connect screen read it."""

    if channel is MarketingChannel.PUSH:
        # Always on, nothing to configure, nothing to disconnect.
        return ConnectionView(
            channel=channel,
            family=channel_family(channel),
            connected=True,
            status=ChannelConnectionStatus.CONNECTED,
            identity="Your app",
            requirements=(),
        )
    if connection is None:
        return ConnectionView(
            channel=channel,
            family=channel_family(channel),
            connected=False,
            status=None,
            requirements=requirements_for(channel),
        )
    return ConnectionView(
        channel=channel,
        family=channel_family(channel),
        connected=connection.is_sendable(),
        status=connection.status,
        config=dict(connection.config or {}),
        identity=_identity(channel, connection.config or {}),
        connected_at=connection.connected_at,
        verified_at=connection.verified_at,
        last_error=connection.last_error,
        requirements=requirements_for(channel),
    )


def all_views(db: Session, *, restaurant_id: uuid.UUID) -> list[ConnectionView]:
    existing = list_connections(db, restaurant_id=restaurant_id)
    return [view_for(channel, existing.get(channel)) for channel in MarketingChannel]


def live_channels(db: Session, *, restaurant_id: uuid.UUID) -> set[MarketingChannel]:
    """Every channel this restaurant can send on right now.

    One query for the whole picker, rather than `is_live` six times.
    """

    existing = list_connections(db, restaurant_id=restaurant_id)
    live = {MarketingChannel.PUSH}
    live |= {
        channel
        for channel, connection in existing.items()
        if connection.is_sendable()
    }
    return live


def connect(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    channel: MarketingChannel,
    values: dict[str, str],
) -> RestaurantChannelConnection:
    """Save (or re-save) what a channel needs, splitting secrets out.

    Re-saving keeps the credentials the owner did not retype. A connect form
    cannot show a stored token, so an owner correcting their sender name would
    otherwise blank the API key by leaving its field empty — and the failure
    would not appear until the next send.
    """

    if channel is MarketingChannel.PUSH:
        raise ConnectionError_(
            "Push notifications are part of your app and are always on — "
            "there is nothing to connect."
        )

    specs = requirements_for(channel)
    if not specs:
        raise ConnectionError_(f"{channel.value.title()} cannot be connected yet.")

    existing = get_connection(db, restaurant_id=restaurant_id, channel=channel)
    config = dict(existing.config or {}) if existing else {}
    credentials = dict(existing.credentials or {}) if existing else {}

    missing: list[str] = []
    for spec in specs:
        raw = values.get(spec.key)
        supplied = (raw or "").strip()
        target = credentials if spec.secret else config
        if supplied:
            target[spec.key] = supplied
        elif spec.required and not target.get(spec.key):
            missing.append(spec.label)

    if missing:
        raise ConnectionError_(
            "Still needed: " + ", ".join(missing) + "."
        )

    now = datetime.now(UTC)
    if existing is None:
        existing = RestaurantChannelConnection(
            id=uuid.uuid4(),
            restaurant_id=restaurant_id,
            channel=channel.value,
            connected_at=now,
        )
        db.add(existing)

    existing.config = config
    existing.credentials = credentials
    existing.status = ChannelConnectionStatus.CONNECTED
    existing.connected_at = existing.connected_at or now
    # Cleared, not kept: the owner has just changed something, so the previous
    # failure describes a configuration that no longer exists.
    existing.last_error = None
    existing.verified_at = None
    db.commit()
    db.refresh(existing)

    logger.info(
        "Channel connected restaurant_id=%s channel=%s", restaurant_id, channel.value
    )
    return existing


def set_enabled(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    channel: MarketingChannel,
    enabled: bool,
) -> RestaurantChannelConnection:
    """Pause or resume a channel without losing its configuration.

    Distinct from disconnecting. An owner pausing WhatsApp for a month should
    not have to re-authorise Meta afterwards.
    """

    connection = get_connection(db, restaurant_id=restaurant_id, channel=channel)
    if connection is None:
        raise ConnectionError_(f"{channel.value.title()} is not connected.")
    connection.status = (
        ChannelConnectionStatus.CONNECTED if enabled else ChannelConnectionStatus.DISABLED
    )
    db.commit()
    db.refresh(connection)
    return connection


def disconnect(
    db: Session, *, restaurant_id: uuid.UUID, channel: MarketingChannel
) -> None:
    """Forget the channel entirely, credentials included."""

    connection = get_connection(db, restaurant_id=restaurant_id, channel=channel)
    if connection is None:
        return
    db.delete(connection)
    db.commit()
    logger.info(
        "Channel disconnected restaurant_id=%s channel=%s", restaurant_id, channel.value
    )


def record_failure(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    channel: MarketingChannel,
    reason: str,
) -> None:
    """Remember that the provider refused us, so the picker can say so.

    Written on a session that may already be dirty from the error being
    handled, so it commits on its own and swallows its own failure — the same
    rule `mark_send_failed` follows, and for the same reason: a bookkeeping
    write must never be what turns a failed send into a stuck one.
    """

    try:
        connection = get_connection(db, restaurant_id=restaurant_id, channel=channel)
        if connection is None:
            return
        connection.status = ChannelConnectionStatus.ERROR
        connection.last_error = reason[:2000]
        db.commit()
    except Exception:  # noqa: BLE001 - never mask the original failure
        logger.exception(
            "Could not record channel failure restaurant_id=%s channel=%s",
            restaurant_id,
            channel.value,
        )
        db.rollback()


def mark_verified(
    db: Session, *, restaurant_id: uuid.UUID, channel: MarketingChannel
) -> None:
    """The credentials were just proven to work against the real provider."""

    connection = get_connection(db, restaurant_id=restaurant_id, channel=channel)
    if connection is None:
        return
    connection.verified_at = datetime.now(UTC)
    connection.status = ChannelConnectionStatus.CONNECTED
    connection.last_error = None
    db.commit()
