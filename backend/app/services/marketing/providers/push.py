"""Push, as a provider — the same Firebase multicast that was in `dispatch`.

Lifted out rather than rewritten. Every rule this code already encoded is
still here: one multicast per batch, a customer with two devices is one person
reached, and a token Firebase rejects as unregistered is deactivated so the
next campaign stops reporting the same failure forever.

It shares `_get_firebase_app` and `_should_deactivate_token` with
`services/notifications.py` and nothing else, which is the boundary the
Marketing Hub has held since it was written: that module 404s an empty
audience and raises `HTTPException` mid-dispatch, both wrong for a background
send, and bending it to serve both would risk the order notifications.
"""

from __future__ import annotations

import logging

from firebase_admin import messaging

from app.config import get_settings
from app.models.enums import MarketingChannel
from app.services.marketing.providers.base import (
    BatchMember,
    BatchResult,
    MemberOutcome,
    ProviderError,
    RenderedMessage,
)
from app.services.notifications import _get_firebase_app, _should_deactivate_token

logger = logging.getLogger(__name__)
settings = get_settings()


class PushProvider:
    channel = MarketingChannel.PUSH

    def addresses_for(self, user) -> list[str]:
        """Device tokens are looked up in bulk by dispatch, not per user here.

        The one channel where the address is not on the user row. Dispatch
        passes tokens in on the `BatchMember`, so this exists to satisfy the
        protocol and is never the source of truth.
        """

        return []

    def max_batch(self) -> int:
        return max(1, settings.marketing_dispatch_batch_size)

    def send(self, members: list[BatchMember], *, message: RenderedMessage) -> BatchResult:
        tokens = [address for member in members for address in member.addresses]
        if not tokens:
            return BatchResult(
                outcomes=[
                    MemberOutcome(user_id=member.user_id, delivered=False, reason="No active device")
                    for member in members
                ]
            )

        app = _get_firebase_app()
        try:
            response = messaging.send_each_for_multicast(
                messaging.MulticastMessage(
                    tokens=tokens,
                    notification=messaging.Notification(title=message.title, body=message.body),
                    data=message.data,
                ),
                app=app,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the owner
            raise ProviderError(
                f"Your app's notification service refused the send: {exc}", retryable=True
            ) from exc

        # Firebase answers per token; the campaign counts per person. A
        # customer whose phone took the message and whose old tablet did not
        # was reached.
        by_token: dict[str, tuple[bool, str | None, bool]] = {}
        for token_value, single in zip(tokens, response.responses, strict=False):
            if single.success:
                by_token[token_value] = (True, None, False)
                continue
            exception = single.exception
            reason = str(exception) if exception is not None else "Unknown Firebase send failure"
            by_token[token_value] = (False, reason, _should_deactivate_token(exception))

        outcomes: list[MemberOutcome] = []
        for member in members:
            results = [by_token.get(address, (False, "Not attempted", False)) for address in member.addresses]
            delivered = any(ok for ok, _, _ in results)
            reason = None if delivered else next((r for ok, r, _ in results if not ok and r), "Delivery failed")
            outcomes.append(
                MemberOutcome(
                    user_id=member.user_id,
                    delivered=delivered,
                    reason=reason,
                    dead_addresses=[
                        address
                        for address in member.addresses
                        if by_token.get(address, (False, None, False))[2]
                    ],
                )
            )
        return BatchResult(outcomes=outcomes)
