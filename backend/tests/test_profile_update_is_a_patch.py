"""Editing your name must not delete your address.

`PATCH /profile/me` wrote every field unconditionally, so a field the client
left out of the body was stored as NULL. `api.updateProfile` in the customer
web app sends exactly two keys — `full_name` and `phone_number` — so every time
a customer corrected their name on the account screen, their saved delivery
address was erased. Silently, and with a success response.

It was found sideways: an end-to-end test's fixture address kept vanishing
between runs, and the test that depended on it `test.skip()`-ed itself green
rather than failing, so nothing said so.

This path had no tests at all, which is how a data-loss bug lived in a
fourteen-line function. These are them.

No database: `update_user_profile` touches the session only to add, commit and
refresh, so a recording stub is enough and the assertions stay about the rule
rather than about SQLAlchemy.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException  # noqa: E402

from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402
from app.schemas.profile import UserProfileUpdateRequest  # noqa: E402
from app.services.profile import update_user_profile  # noqa: E402


class FakeSession:
    """Enough of a Session for a function that only writes one row."""

    def __init__(self) -> None:
        self.committed = 0

    def add(self, _instance: object) -> None:
        pass

    def commit(self) -> None:
        self.committed += 1

    def refresh(self, _instance: object) -> None:
        pass

    def rollback(self) -> None:  # pragma: no cover - only on IntegrityError
        pass


def make_user(**overrides) -> User:
    now = datetime.now(timezone.utc)
    fields = {
        "id": uuid.uuid4(),
        "full_name": "Asha Patel",
        "email": "asha@example.com",
        "phone_number": "9825322860",
        "default_address": "12 Satellite Road, Ahmedabad",
        "role": UserRole.CUSTOMER,
        "is_active": True,
        "is_verified": True,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    return User(**fields)


def patch(user: User, body: dict) -> User:
    """Apply a body exactly as it arrived over the wire.

    `model_validate` on a dict is what FastAPI does, and it is the part that
    matters: it is what populates `model_fields_set`, which is the only way to
    tell a key that was omitted from one that was sent as null. Constructing
    the model with keyword arguments instead would mark every field as set and
    the test would pass while testing nothing.
    """

    update_user_profile(FakeSession(), user, UserProfileUpdateRequest.model_validate(body))
    return user


class OmittedFieldsAreLeftAloneTests(unittest.TestCase):
    def test_editing_a_name_does_not_erase_the_address(self) -> None:
        """The bug, exactly as a customer met it."""

        user = patch(make_user(), {"full_name": "Asha R Patel", "phone_number": "9825322860"})
        self.assertEqual(user.full_name, "Asha R Patel")
        self.assertEqual(user.default_address, "12 Satellite Road, Ahmedabad")

    def test_a_body_with_one_key_changes_one_field(self) -> None:
        user = patch(make_user(), {"default_address": "4 Nehru Bridge, Surat"})
        self.assertEqual(user.default_address, "4 Nehru Bridge, Surat")
        # Untouched, including the name — which used to be mandatory on this
        # request purely because it was always overwritten.
        self.assertEqual(user.full_name, "Asha Patel")
        self.assertEqual(user.phone_number, "9825322860")

    def test_an_empty_body_changes_nothing(self) -> None:
        user = patch(make_user(), {})
        self.assertEqual(user.full_name, "Asha Patel")
        self.assertEqual(user.phone_number, "9825322860")
        self.assertEqual(user.default_address, "12 Satellite Road, Ahmedabad")


class AnExplicitNullStillClearsTests(unittest.TestCase):
    """Absent and null meant the same thing before. They must not now."""

    def test_a_null_phone_clears_it(self) -> None:
        # What the account screen sends when the customer empties that box:
        # `phone_number: phone.trim() || null`. It has to keep working.
        user = patch(make_user(), {"full_name": "Asha Patel", "phone_number": None})
        self.assertIsNone(user.phone_number)
        self.assertEqual(user.default_address, "12 Satellite Road, Ahmedabad")

    def test_a_null_address_clears_it(self) -> None:
        user = patch(make_user(), {"default_address": None})
        self.assertIsNone(user.default_address)

    def test_a_blank_address_clears_it_too(self) -> None:
        # A form that submits "" for an emptied box means the same thing as one
        # that submits null, and a stored "" would print as an empty line on a
        # receipt rather than as no address.
        user = patch(make_user(), {"default_address": "   "})
        self.assertIsNone(user.default_address)


class TheNameCannotBeErasedTests(unittest.TestCase):
    """`users.full_name` is NOT NULL, so clearing it is refused, not ignored."""

    def test_a_null_name_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            patch(make_user(), {"full_name": None})
        self.assertEqual(caught.exception.status_code, 422)

    def test_a_blank_name_is_refused(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            patch(make_user(), {"full_name": "   "})
        self.assertEqual(caught.exception.status_code, 422)

    def test_a_name_that_is_too_short_once_trimmed_is_refused(self) -> None:
        # The check is on the TRIMMED value, which is why it lives in the
        # service rather than in `Field(min_length=2)`: " a " passes a raw
        # length check and is a one-character name.
        with self.assertRaises(HTTPException) as caught:
            patch(make_user(), {"full_name": " a "})
        self.assertEqual(caught.exception.status_code, 422)

    def test_the_refusal_leaves_the_row_alone(self) -> None:
        user = make_user()
        with self.assertRaises(HTTPException):
            patch(user, {"full_name": "", "default_address": "4 Nehru Bridge, Surat"})
        # Nothing was committed, so nothing in the same body took effect — a
        # half-applied update is worse than a refused one.
        self.assertEqual(user.full_name, "Asha Patel")
        self.assertEqual(user.default_address, "12 Satellite Road, Ahmedabad")


class ValuesAreTidiedTests(unittest.TestCase):
    def test_surrounding_whitespace_is_stripped(self) -> None:
        user = patch(make_user(), {"full_name": "  Asha R Patel  "})
        self.assertEqual(user.full_name, "Asha R Patel")


if __name__ == "__main__":
    unittest.main()
