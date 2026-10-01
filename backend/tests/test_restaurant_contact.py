"""A restaurant's contact details, and the placeholders that are not details.

The rule this guards is narrow and easy to lose: onboarding fills four NOT NULL
address columns with placeholders, so the naive read of those columns produces
"Pending restaurant setup, Pending 000000" — and the surface that reads it is
the footer of every page of a live website. An absent address is honest; a
printed placeholder is a claim about a real business.

Pure, so it needs no database: `read_contact` takes a Restaurant instance and
returns a dict. Constructing the model unsaved is enough.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.restaurant import (  # noqa: E402
    PLACEHOLDER_ADDRESS,
    PLACEHOLDER_CITY,
    PLACEHOLDER_POSTAL_CODE,
    PLACEHOLDER_STATE,
    Restaurant,
)
from app.services.restaurant_contact import read_contact  # noqa: E402


def make(**overrides) -> Restaurant:
    fields = {
        "name": "Radhe Dhokla",
        "address_line_1": "12 Satellite Road",
        "address_line_2": None,
        "city": "Ahmedabad",
        "state": "Gujarat",
        "postal_code": "380015",
        "country": "India",
        "phone_number": "+919876543210",
    }
    fields.update(overrides)
    return Restaurant(**fields)


class ReadContactTests(unittest.TestCase):
    def test_a_filled_in_restaurant_reads_as_an_envelope(self) -> None:
        contact = read_contact(make())
        self.assertEqual(
            contact["address"],
            "12 Satellite Road, Ahmedabad, Gujarat 380015",
        )
        self.assertEqual(contact["phone"], "+919876543210")
        self.assertEqual(contact["city"], "Ahmedabad")
        # The country is on the record but deliberately out of the one-line
        # form: a customer ordering delivery knows which country they are in.
        self.assertEqual(contact["country"], "India")
        self.assertNotIn("India", contact["address"])

    def test_the_second_address_line_joins_in_when_there_is_one(self) -> None:
        contact = read_contact(make(address_line_2="Shop 4, Mandir Complex"))
        self.assertEqual(
            contact["address"],
            "12 Satellite Road, Shop 4, Mandir Complex, Ahmedabad, Gujarat 380015",
        )

    def test_a_freshly_onboarded_restaurant_has_no_contact_details(self) -> None:
        """The case that matters. Every address column is a placeholder."""

        contact = read_contact(
            make(
                address_line_1=PLACEHOLDER_ADDRESS,
                city=PLACEHOLDER_CITY,
                state=PLACEHOLDER_STATE,
                postal_code=PLACEHOLDER_POSTAL_CODE,
                phone_number=None,
            )
        )
        # The country defaults to India on every row, so it survives — it is
        # not a placeholder. Nothing else does, and critically there is no
        # `address` key at all rather than an address made of nothing.
        self.assertNotIn("address", contact)
        self.assertNotIn("city", contact)
        self.assertNotIn("phone", contact)
        for value in contact.values():
            self.assertNotIn("Pending", value)
            self.assertNotEqual(value, PLACEHOLDER_POSTAL_CODE)

    def test_one_real_part_among_placeholders_still_comes_through(self) -> None:
        """Half-filled is the normal state partway through onboarding."""

        contact = read_contact(
            make(
                address_line_1=PLACEHOLDER_ADDRESS,
                state=PLACEHOLDER_STATE,
                postal_code=PLACEHOLDER_POSTAL_CODE,
            )
        )
        self.assertEqual(contact["address"], "Ahmedabad")
        self.assertEqual(contact["city"], "Ahmedabad")

    def test_blank_and_whitespace_are_absences_too(self) -> None:
        contact = read_contact(make(phone_number="   ", address_line_2=""))
        self.assertNotIn("phone", contact)
        self.assertNotIn("address_line_2", contact)

    def test_a_pasted_value_is_collapsed_rather_than_stored_with_its_newline(self) -> None:
        # These come out of spreadsheets. A newline inside the footer's address
        # line is the sort of thing nobody sees until it is on a phone.
        contact = read_contact(make(address_line_1="12  Satellite\nRoad"))
        self.assertEqual(contact["address_line_1"], "12 Satellite Road")


if __name__ == "__main__":
    unittest.main()
