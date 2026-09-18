"""Which features are on for which restaurant.

**Read this before adding an entry.** A per-restaurant allowlist existed in
this codebase and was deliberately deleted. `insights/tool_chat.py:135` still
carries the note:

> There used to be an allowlist of restaurant ids beside this. It was meant as
> a rollout dial and **became a permanent split**: one restaurant got the data
> tools and every other owner got a thinner assistant, **with nothing on
> screen to explain why**.

Invisibility was the symptom. The fatal property was that the dial had no
owner, no writer and no lifecycle: it was a module constant — a build-time
artifact — expressing a commercial fact. Nothing outside the code could see
it, nothing could change it without a deploy, and nothing ever forced anyone
to revisit it.

Four properties fix that, none of which rely on anyone remembering:

1. **A different home and a different writer.** A capability is a database row
   written by a platform admin through an authenticated endpoint, carrying who
   granted it and when. It is *impossible* to express "restaurant X only" in
   `settings.py`, because settings has no restaurant-shaped store.
2. **Registration precedes storage.** This catalog is the only source of valid
   keys and the write endpoint refuses anything else. Every entry **requires**
   an `owner_description` — you cannot add a capability without writing the
   sentence the owner reads, which is what makes invisibility structurally
   impossible.
3. **Resolution returns a reason, not a boolean.** See `CapabilityDecision`.
   Throwing the reason away takes an explicit `.enabled`.
4. **A test shaped like the old mistake**, asserting no module outside the
   resolver compares a restaurant id against a literal.

The line for what belongs here is **owner-perceptibility**: if an owner could
notice the difference and a salesperson could price it, it is a capability. If
the difference is invisible to the owner — a model name, a timeout, a router
toggle — it stays a global dial in `settings.py` forever.

And never gate correctness. A flag gates extra capability, never a fix: a bug
fixed behind a flag is a bug still live for everyone else.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CapabilityReason(StrEnum):
    """Why a capability resolved the way it did.

    Rendered on both the operator's screen and the owner's, because "off" with
    no reason is exactly the state that made the deleted allowlist harmful.
    """

    GRANTED = "granted"
    REVOKED = "revoked"
    DEFAULT_ON = "default_on"
    DEFAULT_OFF = "default_off"
    BUILD_FLAG_OFF = "build_flag_off"


@dataclass(frozen=True)
class Capability:
    """One switchable feature, described in the words the owner reads."""

    key: str
    label: str
    # What the restaurant's owner is told this does. Required, and the reason
    # this catalog is a dataclass rather than a set of strings.
    owner_description: str
    # What a restaurant with no row gets. Onboarding writes no rows, so this
    # is what every new tenant starts on.
    default: bool
    # The deployment-wide kill switch, if the feature has one. It can only
    # subtract: global off with the tenant on is off, and the screen says so.
    global_flag: str | None
    # Whether the customer-facing clients are told about it. An operator-only
    # capability never leaves the admin API.
    client_visible: bool


CAPABILITIES: dict[str, Capability] = {
    "ask_ai": Capability(
        key="ask_ai",
        label="Ask AI",
        owner_description=(
            "Customers can ask your menu questions in plain language — what is "
            "spicy, what suits a group, what goes with what — and order from the "
            "answer. Turned off, the storefront hides it entirely."
        ),
        # On by default: every restaurant has had this since before it was
        # switchable, and turning it off for existing tenants by shipping this
        # catalog would be a feature removal disguised as a refactor.
        default=True,
        global_flag=None,
        client_visible=True,
    ),
}

CAPABILITY_KEYS = frozenset(CAPABILITIES)

# Bumped when a default changes, to invalidate every cached resolution at
# once. A stale "on" after a default flips to off is the expensive direction.
CATALOG_VERSION = 1


@dataclass(frozen=True)
class CapabilityDecision:
    """Whether a capability is on, and why.

    A bare boolean is what the old allowlist handed out, and it is why nobody
    could explain the difference between two restaurants. Reading `.enabled`
    and dropping `.reason` is allowed — it just has to be written down.
    """

    key: str
    enabled: bool
    reason: CapabilityReason

    @property
    def explanation(self) -> str:
        """The reason as a sentence, for either screen."""

        return {
            CapabilityReason.GRANTED: "Switched on for this restaurant.",
            CapabilityReason.REVOKED: "Switched off for this restaurant.",
            CapabilityReason.DEFAULT_ON: "On by default for every restaurant.",
            CapabilityReason.DEFAULT_OFF: "Off by default; ask to have it enabled.",
            CapabilityReason.BUILD_FLAG_OFF: (
                "Unavailable on this deployment, so it stays off even where it "
                "has been granted."
            ),
        }[self.reason]


__all__ = [
    "CAPABILITIES",
    "CAPABILITY_KEYS",
    "CATALOG_VERSION",
    "Capability",
    "CapabilityDecision",
    "CapabilityReason",
]
