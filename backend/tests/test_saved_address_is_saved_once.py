"""Saving the same doorstep twice gives you one address, not two.

Observed in the live database on 2026-10-03: two rows for one customer,
byte-identical in every column including their coordinates —

    address_line_1 = '12 Velanja - Gothan Road'
    city = 'Surat'  state = 'Gujarat'  postal_code = '394150'
    latitude = 21.3026097  longitude = 72.9159345

and two cards reading the same street in the checkout's address picker.

There *was* a guard against this, and it was in the wrong place. The checkout
compares the typed address against the picker's list before saving
(`isSameAddress` in `frontend-customer/src/lib/delivery-address.ts`), but that
list is a cached query: the first order writes the row, the cache does not know
about it yet, and a second order the same evening finds no match and writes it
again. Every client can lose that race and there are three of them, so the rule
belongs on the server, where there is only one copy of it.

The fingerprint deliberately ignores the label and the phone number. The same
doorstep saved once as HOME and once as WORK is still one doorstep, and a
customer correcting their phone number should not acquire a second copy of
their house.

No database: the duplicate path returns before `db.add`, so a session that can
only answer `scalars` is enough, and the assertions stay about the rule rather
than about SQLAlchemy.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_saved_address import UserSavedAddress  # noqa: E402
from app.schemas.order import DeliveryQuoteRequest, OrderCreateRequest  # noqa: E402
from app.schemas.profile import SavedAddressCreateRequest  # noqa: E402
from app.services.profile import (  # noqa: E402
    _address_fingerprint,
    _matching_saved_address,
    create_user_saved_address,
)


def make_user() -> User:
    now = datetime.now(timezone.utc)
    return User(
        id=uuid.uuid4(),
        full_name="Asha Patel",
        email="asha@example.com",
        phone_number="9825322860",
        role=UserRole.CUSTOMER,
        is_active=True,
        is_verified=True,
        created_at=now,
        updated_at=now,
    )


def make_saved(user: User, **overrides) -> UserSavedAddress:
    now = datetime.now(timezone.utc)
    fields = {
        "id": uuid.uuid4(),
        "user_id": user.id,
        "label": "OTHER",
        "address_line_1": "12 Velanja - Gothan Road",
        "address_line_2": None,
        "landmark": None,
        "city": "Surat",
        "state": "Gujarat",
        "postal_code": "394150",
        "phone_number": None,
        "latitude": 21.3026097,
        "longitude": 72.9159345,
        "is_default": True,
        "created_at": now,
        "updated_at": now,
    }
    fields.update(overrides)
    return UserSavedAddress(**fields)


def make_payload(**overrides) -> SavedAddressCreateRequest:
    fields = {
        "label": "OTHER",
        "address_line_1": "12 Velanja - Gothan Road",
        "city": "Surat",
        "state": "Gujarat",
        "postal_code": "394150",
    }
    fields.update(overrides)
    return SavedAddressCreateRequest.model_validate(fields)


class FakeSession:
    """Enough of a Session to read one customer's addresses back.

    `add`, `flush` and `commit` are recorded rather than ignored, because the
    whole point of these tests is that the duplicate path does not reach them.
    """

    def __init__(self, rows: list[UserSavedAddress]) -> None:
        self.rows = rows
        self.added: list[object] = []
        self.commits = 0

    def scalars(self, _statement):  # noqa: ANN001 - a stub, not the real API
        return _Scalars(self.rows)

    def scalar(self, _statement):  # noqa: ANN001 - the geocode cache looks here
        # A miss. `locate_saved_address` runs on the path that writes a NEW
        # address and consults the geocode cache; answering None keeps that
        # path on its no-provider branch instead of raising inside a logger.
        return None

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def flush(self) -> None:
        # Stand in for the server defaults. Without them the new row cannot be
        # serialized, and the test for "a genuinely new address is still
        # written" would fail for a reason that has nothing to do with the rule.
        now = datetime.now(timezone.utc)
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()
                row.created_at = now
                row.updated_at = now

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _instance: object) -> None:
        pass

    def begin_nested(self):  # noqa: ANN202 - the geocode cache writes in one
        return _NoSavepoint()

    def rollback(self) -> None:  # pragma: no cover - no error path here
        pass


class _NoSavepoint:
    """A savepoint that does nothing, for the path that writes a new row."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *_exc: object) -> bool:
        return False


class _Scalars:
    def __init__(self, rows: list[UserSavedAddress]) -> None:
        self._rows = rows

    def all(self) -> list[UserSavedAddress]:
        return list(self._rows)


class TheFingerprintIsAboutThePlace(unittest.TestCase):
    def test_spacing_and_case_do_not_make_a_second_address(self) -> None:
        # A customer re-picking the same Google suggestion gets subtly
        # different whitespace each time, which is how an equality check on
        # raw strings lets a duplicate through.
        self.assertEqual(
            _address_fingerprint("12 Velanja - Gothan Road", None, None, "Surat", "GJ", "394150"),
            _address_fingerprint(
                "  12   Velanja  -  Gothan  Road ", "", "", "surat", "gj", " 394150 "
            ),
        )

    def test_a_missing_part_and_an_empty_part_are_the_same(self) -> None:
        # The column is NULL and the form sends "". Treating those as
        # different is exactly how the first duplicate was written.
        self.assertEqual(
            _address_fingerprint("A3 Dhansora Road", None, None, "Surat", "Gujarat", "395004"),
            _address_fingerprint("A3 Dhansora Road", "", "", "Surat", "Gujarat", "395004"),
        )

    def test_a_different_flat_is_a_different_address(self) -> None:
        self.assertNotEqual(
            _address_fingerprint("A3 Dhansora Road", None, None, "Surat", "Gujarat", "395004"),
            _address_fingerprint("A4 Dhansora Road", None, None, "Surat", "Gujarat", "395004"),
        )

    def test_the_second_line_is_part_of_the_place(self) -> None:
        # Two flats on one road differ only here, and the picker renders the
        # line — so collapsing them would hide a real address.
        self.assertNotEqual(
            _address_fingerprint("Main Road", "Millenium Park", None, "Surat", "GJ", "394210"),
            _address_fingerprint("Main Road", "Shanti Park", None, "Surat", "GJ", "394210"),
        )


class TheMatchIgnoresWhatIsNotThePlace(unittest.TestCase):
    def setUp(self) -> None:
        self.user = make_user()

    def test_a_different_label_still_matches(self) -> None:
        saved = make_saved(self.user, label="HOME")
        match = _matching_saved_address([saved], make_payload(label="WORK"))
        self.assertIs(match, saved)

    def test_a_different_phone_number_still_matches(self) -> None:
        saved = make_saved(self.user, phone_number="9825322860")
        match = _matching_saved_address([saved], make_payload(phone_number="9687278179"))
        self.assertIs(match, saved)

    def test_a_genuinely_new_address_matches_nothing(self) -> None:
        saved = make_saved(self.user)
        match = _matching_saved_address([saved], make_payload(address_line_1="A3 Dhansora Road"))
        self.assertIsNone(match)

    def test_an_empty_list_matches_nothing(self) -> None:
        self.assertIsNone(_matching_saved_address([], make_payload()))


class SavingItAgainReturnsTheOneYouHave(unittest.TestCase):
    def setUp(self) -> None:
        self.user = make_user()

    def test_no_second_row_is_written(self) -> None:
        saved = make_saved(self.user)
        db = FakeSession([saved])

        response = create_user_saved_address(db, self.user, make_payload())

        # The bug, stated: this used to be a second row.
        self.assertEqual(db.added, [])
        self.assertEqual(response.id, saved.id)

    def test_the_caller_gets_an_id_it_can_put_on_an_order(self) -> None:
        # The checkout saves an address in order to attach it to the order it
        # is placing. Refusing the save outright would have broken that, which
        # is why this returns the existing address rather than an error.
        saved = make_saved(self.user)
        db = FakeSession([saved])

        response = create_user_saved_address(db, self.user, make_payload())

        self.assertEqual(response.id, saved.id)
        self.assertEqual(response.latitude, saved.latitude)
        self.assertEqual(response.longitude, saved.longitude)

    def test_a_re_save_fills_in_a_missing_phone_number(self) -> None:
        saved = make_saved(self.user, phone_number=None)
        db = FakeSession([saved])

        create_user_saved_address(db, self.user, make_payload(phone_number="9687278179"))

        self.assertEqual(saved.phone_number, "9687278179")
        self.assertEqual(db.added, [])

    def test_a_re_save_does_not_overwrite_a_phone_number(self) -> None:
        # The stored number may be the one a courier has already called. A
        # re-save fills a gap; it does not get to replace what is there.
        saved = make_saved(self.user, phone_number="9825322860")
        db = FakeSession([saved])

        create_user_saved_address(db, self.user, make_payload(phone_number="9687278179"))

        self.assertEqual(saved.phone_number, "9825322860")

    def test_an_unchanged_re_save_writes_nothing_at_all(self) -> None:
        # The common case: the checkout sends the address on every order, so
        # the usual re-save should cost no write. Not a performance point —
        # a commit here would bump `updated_at` on a row nobody edited, and
        # that column is what a consent or delivery audit reads as "when did
        # this change".
        saved = make_saved(self.user, phone_number="9825322860")
        db = FakeSession([saved])

        create_user_saved_address(db, self.user, make_payload())

        self.assertEqual(db.commits, 0)
        self.assertEqual(db.added, [])

    def test_a_new_address_is_still_written(self) -> None:
        saved = make_saved(self.user)
        db = FakeSession([saved])

        create_user_saved_address(db, self.user, make_payload(address_line_1="A3 Dhansora Road"))

        self.assertEqual(len(db.added), 1)


class TheOrderCanBePlacedToASavedAddress(unittest.TestCase):
    """The other half of the same screenshot.

    The checkout refused the order with "Please choose your address from the
    suggestions" while a saved address was selected on screen. Two causes, one
    on each side: `applySavedAddress` filled the form and left `pickedPoint`
    null, and the order request had no way to name the saved address even
    though the delivery QUOTE has taken one since the autocomplete was built.

    So the quote priced a saved address from its stored rooftop and the order
    refused the very same address for carrying no coordinates.
    """

    def test_both_requests_can_name_a_saved_address(self) -> None:
        self.assertIn("saved_address_id", DeliveryQuoteRequest.model_fields)
        # The half that was missing.
        self.assertIn("saved_address_id", OrderCreateRequest.model_fields)

    def test_naming_one_is_optional(self) -> None:
        # The WhatsApp agent and the mobile app collect an address as text and
        # have no list to pick from. Requiring this would refuse them.
        self.assertIsNone(OrderCreateRequest.model_fields["saved_address_id"].default)

    def test_an_unreadable_address_table_refuses_rather_than_crashing(self) -> None:
        """A 500 on the Pay button is worse than a 422 beside the address.

        This lookup is NEW on the order path: before the fallback existed,
        placing an order never touched `user_saved_addresses`. The table can
        be absent on an environment that has not run the migrations —
        `services/profile.py` carries a whole fail-open path for exactly that
        — so letting the error through would have turned a clean refusal into
        a crash at the last step of a checkout.

        Asserted on the source rather than by standing up a broken database,
        because what is being checked is that the call is guarded at all.
        """
        source = (
            Path(__file__).resolve().parents[1] / "app" / "services" / "orders.py"
        ).read_text(encoding="utf-8")
        lookup = source.index("db.get(UserSavedAddress, payload.saved_address_id)")
        # The `try` opens within a few lines above the call, and a rollback
        # follows — a bare `except` that left the session dirty would break
        # the commit that places the order.
        window = source[max(0, lookup - 400) : lookup + 600]
        self.assertIn("try:", window)
        self.assertIn("except SQLAlchemyError:", window)
        self.assertIn("db.rollback()", window)
        # And it must still refuse, rather than pricing from nothing.
        self.assertIn("if known_drop is None and require_payment_validation:", source)

    def test_a_saved_address_carries_its_coordinates_to_the_client(self) -> None:
        # The server has returned these all along; the storefront's own
        # `SavedAddress` type did not declare them, so the checkout could not
        # read them and sent no coordinates for an address it had.
        user = make_user()
        saved = make_saved(user)
        db = FakeSession([saved])
        response = create_user_saved_address(db, user, make_payload())
        self.assertIsNotNone(response.latitude)
        self.assertIsNotNone(response.longitude)


if __name__ == "__main__":
    unittest.main()
