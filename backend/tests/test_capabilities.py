"""Features switched on for one restaurant, without a fork.

A per-restaurant allowlist existed in this codebase and was deliberately
deleted. `insights/tool_chat.py` still carries the note: it "became a
permanent split: one restaurant got the data tools and every other owner got a
thinner assistant, **with nothing on screen to explain why**."

So the tests that matter are not "does the flag work". They are the four
properties that make this different from the thing that was removed:

- **No rows changes nothing.** Shipping the catalog must be a no-op for every
  restaurant that already exists, or it is a feature removal in disguise.
- **A decision is not the same as a default.** "Off" and "nobody has looked"
  are different facts, and an operator needs to tell them apart when a default
  later changes under them.
- **Resolution carries a reason.** A bare boolean is what the allowlist handed
  out, and it is why nobody could explain the difference between two
  restaurants.
- **The old shape cannot grow back.** `NoRestaurantAllowlistTests` fails if
  any module outside the resolver starts comparing a restaurant id against a
  literal — the exact silhouette of the deleted code.
"""

from __future__ import annotations

import pathlib
import re
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config.capabilities import (
    CAPABILITIES,
    CapabilityReason,
)
from app.services import capabilities as service
from app.services.capabilities import (
    UnknownCapability,
    client_capabilities,
    resolve_capabilities,
    validate_capability_key,
)


class FakeSession:
    """A session that answers the capability query with the rows given."""

    def __init__(self, rows: list[tuple[str, bool]] | None = None) -> None:
        self.rows = rows or []

    def execute(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: list(self.rows))


class NoRowsChangesNothingTests(unittest.TestCase):
    def test_a_restaurant_with_no_rows_gets_the_catalog_defaults(self) -> None:
        decisions = resolve_capabilities(FakeSession(), restaurant_id=uuid.uuid4())

        self.assertEqual(set(decisions), set(CAPABILITIES))
        for key, capability in CAPABILITIES.items():
            self.assertEqual(decisions[key].enabled, capability.default, key)

    def test_ask_ai_is_on_by_default(self) -> None:
        """Every restaurant has had this since before it was switchable.

        Shipping the catalog with it off would have removed a live feature
        from every tenant under the cover of a refactor.
        """

        decisions = resolve_capabilities(FakeSession(), restaurant_id=uuid.uuid4())
        self.assertTrue(decisions["ask_ai"].enabled)
        self.assertEqual(decisions["ask_ai"].reason, CapabilityReason.DEFAULT_ON)

    def test_the_marketplace_has_no_grants(self) -> None:
        decisions = resolve_capabilities(FakeSession(), restaurant_id=None)
        self.assertTrue(decisions["ask_ai"].enabled)
        self.assertEqual(decisions["ask_ai"].reason, CapabilityReason.DEFAULT_ON)


class ADecisionIsNotADefaultTests(unittest.TestCase):
    def test_granting_says_granted_not_default(self) -> None:
        decisions = resolve_capabilities(
            FakeSession([("ask_ai", True)]), restaurant_id=uuid.uuid4()
        )
        self.assertTrue(decisions["ask_ai"].enabled)
        # Distinct from DEFAULT_ON even though both are "on": one is a decision
        # somebody made, the other is what happens when nobody has looked.
        self.assertEqual(decisions["ask_ai"].reason, CapabilityReason.GRANTED)

    def test_revoking_turns_it_off_for_that_restaurant(self) -> None:
        decisions = resolve_capabilities(
            FakeSession([("ask_ai", False)]), restaurant_id=uuid.uuid4()
        )
        self.assertFalse(decisions["ask_ai"].enabled)
        self.assertEqual(decisions["ask_ai"].reason, CapabilityReason.REVOKED)

    def test_every_reason_has_a_sentence(self) -> None:
        """The reason is rendered, not logged. An unexplained one is the bug."""

        for reason in CapabilityReason:
            decision = service.CapabilityDecision("ask_ai", True, reason)
            self.assertTrue(decision.explanation.strip(), reason)


class TheGlobalFlagCanOnlySubtractTests(unittest.TestCase):
    def test_a_build_flag_off_beats_a_grant_and_says_why(self) -> None:
        """A deployment without the feature keeps it off even where granted.

        And the operator is told, rather than being shown a switch that does
        nothing — which is how a support call becomes an afternoon.
        """

        with patch.object(service, "_global_allows", lambda key: False):
            decisions = resolve_capabilities(
                FakeSession([("ask_ai", True)]), restaurant_id=uuid.uuid4()
            )

        self.assertFalse(decisions["ask_ai"].enabled)
        self.assertEqual(decisions["ask_ai"].reason, CapabilityReason.BUILD_FLAG_OFF)


class WhatTheClientIsToldTests(unittest.TestCase):
    def test_only_the_answer_travels(self) -> None:
        told = client_capabilities(FakeSession([("ask_ai", False)]), restaurant_id=uuid.uuid4())
        self.assertEqual(told, {"ask_ai": False})

    def test_operator_only_capabilities_never_leave_the_admin_api(self) -> None:
        told = client_capabilities(FakeSession(), restaurant_id=uuid.uuid4())
        for key in told:
            self.assertTrue(CAPABILITIES[key].client_visible, key)


class RegistrationPrecedesStorageTests(unittest.TestCase):
    def test_an_unregistered_key_is_refused(self) -> None:
        """A capability that exists only as a row has no label and no screen.

        Which is exactly the shape of the mistake this replaced, so the write
        path refuses it rather than storing it.
        """

        with self.assertRaises(UnknownCapability):
            validate_capability_key("make_me_rich")

    def test_a_key_is_normalised_before_it_is_matched(self) -> None:
        self.assertEqual(validate_capability_key("  ASK_AI  "), "ask_ai")

    def test_every_catalog_entry_carries_the_sentence_the_owner_reads(self) -> None:
        """This is what makes invisibility structurally impossible.

        You cannot add a capability without writing what the owner is told it
        does, because the dataclass requires it and this asserts it is real.
        """

        for key, capability in CAPABILITIES.items():
            self.assertTrue(capability.label.strip(), key)
            self.assertGreater(len(capability.owner_description.strip()), 30, key)

    def test_a_stored_key_that_left_the_catalog_is_ignored_not_surfaced(self) -> None:
        # Deleting a capability must not make a screen fail to render.
        decisions = resolve_capabilities(
            FakeSession([("ask_ai", False), ("removed_feature", True)]),
            restaurant_id=uuid.uuid4(),
        )
        self.assertNotIn("removed_feature", decisions)
        self.assertFalse(decisions["ask_ai"].enabled)


class NoRestaurantAllowlistTests(unittest.TestCase):
    """The only mechanical guard against the deleted mistake growing back.

    The allowlist was a module constant comparing `restaurant.id` against a
    set of literals. This looks for that silhouette anywhere outside the
    resolver — a UUID literal in a source file that also mentions a restaurant
    id — and fails if one appears.

    A test, rather than a comment, because the last one had a comment.
    """

    # Where a restaurant-shaped decision is allowed to live.
    ALLOWED = {
        pathlib.Path("app/services/capabilities.py"),
        pathlib.Path("app/config/capabilities.py"),
    }
    UUID_LITERAL = re.compile(
        r"['\"][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}['\"]",
        re.I,
    )

    def test_no_module_pins_behaviour_to_a_restaurant_id(self) -> None:
        root = pathlib.Path(__file__).resolve().parent.parent
        offenders: list[str] = []

        for path in (root / "app").rglob("*.py"):
            relative = path.relative_to(root)
            if relative in self.ALLOWED:
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            if "restaurant" not in source.lower():
                continue
            for match in self.UUID_LITERAL.finditer(source):
                line_start = source.rfind("\n", 0, match.start()) + 1
                line = source[line_start : source.find("\n", match.start())]
                if "restaurant" in line.lower():
                    offenders.append(f"{relative}: {line.strip()[:90]}")

        self.assertEqual(
            offenders,
            [],
            "A restaurant id pinned in source is how the deleted allowlist looked. "
            "Put the decision in `restaurant_capabilities` instead.",
        )


if __name__ == "__main__":
    unittest.main()
