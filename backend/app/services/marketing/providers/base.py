"""The contract every channel's sender implements, and nothing more.

`dispatch.py` used to be Firebase code with a campaign wrapped around it. Now
it owns the parts that are true of every send — recompute the audience, write
a recipient row per customer, group by rendered copy, commit progress per
batch, decide the terminal status — and knows nothing about how any particular
channel actually delivers. That knowledge lives behind these two protocols.

The split is DIRECT versus SOCIAL, and it is not stylistic:

    DirectProvider   takes a list of people and a rendered message, and
                     reports per person whether it arrived. Push, WhatsApp,
                     SMS, email.

    SocialProvider   takes one piece of content and publishes it once, to
                     nobody in particular, and reports back an id and a
                     permalink. Instagram, Facebook.

A social provider has no `send` and a direct provider has no `publish`,
because a post has no recipients and a message has no permalink. Forcing both
through one interface would mean every implementation carrying a method that
raises, and `dispatch` guessing which half of the object it holds.

**Every provider fails by raising `ProviderError` with a sentence an owner can
read.** Not a stack trace, not a provider error code: the string lands in
`campaign.last_error` and then on the owner's screen, and "WhatsApp rejected
the message layout — it may not be approved yet" is actionable where
`(#132001) Template name does not exist` is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.models.enums import MarketingChannel


class ProviderError(Exception):
    """A channel refused, with a reason written for the owner.

    `retryable` distinguishes "the provider is down" from "your token is
    wrong". Only the first is worth trying again, and telling an owner to
    retry a credential problem wastes their afternoon.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class BatchMember:
    """One customer, and every address this channel can reach them at.

    A list rather than one address because push is genuinely one-to-many: a
    customer with a phone and a tablet has two tokens and is still one person.
    Every other direct channel puts exactly one entry in here, and the
    dispatch loop does not need to know which is which.
    """

    user_id: uuid.UUID
    addresses: list[str]


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    """The copy as this group of customers will see it, merge fields resolved.

    `extra` is the campaign's per-channel bag — the photo, the approved
    layout id, the hashtags. Carried through untouched by everything between
    the editor and here, and read only by the provider that understands it.
    """

    title: str
    body: str
    data: dict[str, str] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)


@dataclass(slots=True)
class MemberOutcome:
    """What happened to one customer's copy of one message."""

    user_id: uuid.UUID
    delivered: bool
    reason: str | None = None
    #: Addresses the provider says are gone for good — an uninstalled app, a
    #: hard-bounced mailbox. Deactivated so every future campaign stops
    #: reporting the same failure forever.
    dead_addresses: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BatchResult:
    outcomes: list[MemberOutcome] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SocialContent:
    """One public post, as every social network needs it stated."""

    caption: str
    image_url: str | None = None
    link_url: str | None = None
    cta_label: str | None = None
    hashtags: str | None = None
    #: Hashtags in the first comment keeps the caption clean — an IG habit
    #: that is a real API call (a second request), not a formatting choice.
    hashtags_in_comment: bool = False


@dataclass(slots=True)
class PublishResult:
    post_id: str
    permalink: str | None = None


@runtime_checkable
class DirectProvider(Protocol):
    """Sends a rendered message to named people."""

    channel: MarketingChannel

    def addresses_for(self, user) -> list[str]:
        """Where this customer can be reached, or an empty list.

        Empty is not a failure: a customer with no phone number was never
        attempted and nothing went wrong, which is why dispatch records them
        SKIPPED rather than FAILED.
        """
        ...

    def max_batch(self) -> int:
        """How many people may go in one call to the provider."""
        ...

    def send(self, members: list[BatchMember], *, message: RenderedMessage) -> BatchResult:
        """Deliver to everyone in the batch, reporting per person."""
        ...


@runtime_checkable
class SocialProvider(Protocol):
    """Publishes one post, to nobody in particular."""

    channel: MarketingChannel

    def publish(self, content: SocialContent) -> PublishResult:
        ...

    def insights(self, post_id: str) -> dict[str, int]:
        """Impressions, reach, likes — whatever the platform will tell us.

        Returns what it got rather than a fixed shape: a platform that stops
        serving a metric should make it disappear from the report, not report
        it as zero. Zero and "not available" are different facts and an owner
        reading a zero would conclude their post failed.
        """
        ...


def skipped_outcome(user_id: uuid.UUID, reason: str) -> MemberOutcome:
    return MemberOutcome(user_id=user_id, delivered=False, reason=reason)
