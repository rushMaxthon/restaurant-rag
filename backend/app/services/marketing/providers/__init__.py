"""Choosing the sender for a channel, from that restaurant's connection.

One function, and it is the only place that knows which class implements
which channel. `dispatch` asks for a provider and gets one or a
`ProviderError` explaining what the owner still has to do — it never branches
on the channel itself, which is what stopped the old push-shaped dispatch
from being six copies of itself.

Push is the deliberate exception with no connection row: its credentials are
the platform's Firebase service account, shared by every restaurant.
"""

from __future__ import annotations

from app.models.enums import MarketingChannel
from app.models.restaurant_channel_connection import RestaurantChannelConnection
from app.services.marketing.providers.base import (
    BatchMember,
    BatchResult,
    DirectProvider,
    MemberOutcome,
    ProviderError,
    PublishResult,
    RenderedMessage,
    SocialContent,
    SocialProvider,
)
from app.services.marketing.providers.email import EmailProvider
from app.services.marketing.providers.meta_social import (
    FacebookProvider,
    InstagramProvider,
)
from app.services.marketing.providers.push import PushProvider
from app.services.marketing.providers.sms import SmsProvider
from app.services.marketing.providers.whatsapp import WhatsAppProvider

#: Channel to implementation. A channel absent from here cannot send, which is
#: reported as "not supported yet" rather than crashing mid-dispatch.
_BUILDERS = {
    MarketingChannel.WHATSAPP: WhatsAppProvider,
    MarketingChannel.SMS: SmsProvider,
    MarketingChannel.EMAIL: EmailProvider,
    MarketingChannel.INSTAGRAM: InstagramProvider,
    MarketingChannel.FACEBOOK: FacebookProvider,
}


def provider_for(
    channel: MarketingChannel,
    connection: RestaurantChannelConnection | None,
):
    """The sender for this channel, or a `ProviderError` saying why not.

    The connection is read here and nowhere else, so a provider never sees a
    database row — it is constructed from a config dict and a credentials
    dict, which is also what makes every one of them testable without one.
    """

    if channel is MarketingChannel.PUSH:
        return PushProvider()

    builder = _BUILDERS.get(channel)
    if builder is None:
        raise ProviderError(f"{channel.value.title()} cannot send yet.")
    if connection is None:
        raise ProviderError(
            f"{channel.value.title()} is not connected. Connect it and this campaign "
            "will be ready to send."
        )
    if not connection.is_sendable():
        raise ProviderError(
            f"{channel.value.title()} is switched off. Turn it back on to send this."
        )
    return builder(
        config=dict(connection.config or {}),
        credentials=dict(connection.credentials or {}),
    )


__all__ = [
    "BatchMember",
    "BatchResult",
    "DirectProvider",
    "EmailProvider",
    "FacebookProvider",
    "InstagramProvider",
    "MemberOutcome",
    "ProviderError",
    "PublishResult",
    "PushProvider",
    "RenderedMessage",
    "SmsProvider",
    "SocialContent",
    "SocialProvider",
    "WhatsAppProvider",
    "provider_for",
]
