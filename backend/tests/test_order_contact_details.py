"""The name and phone a customer types at checkout must survive the request.

The form demanded both, marked them required, and told the customer they were
how the rider would reach them. `OrderCreateRequest` carried neither, so both
were dropped on submit. Validating a phone number that is then discarded is
theatre, so the contract comes first and the form's validation follows it.

Phone numbers are normalised rather than merely accepted: the same number typed
as "(415) 555-0132", "415-555-0132" and "+1 415 555 0132" has to reach the
kitchen in one shape, or two identical numbers look like two different people.
"""

from __future__ import annotations

import unittest
import uuid

from pydantic import ValidationError

from app.main import app  # noqa: F401 - imported first to settle import order
from app.schemas.order import OrderCreateRequest


def order(**over) -> dict:
    payload = {
        "restaurant_id": uuid.uuid4(),
        "items": [{"menu_item_id": uuid.uuid4(), "quantity": 1}],
        "delivery_address": "1 Test Street, Springfield",
    }
    payload.update(over)
    return payload


class ContactDetailsReachTheServerTests(unittest.TestCase):
    def test_a_name_and_phone_are_accepted_and_kept(self) -> None:
        parsed = OrderCreateRequest(**order(contact_name="Ada Lovelace", contact_phone="4155550132"))
        self.assertEqual(parsed.contact_name, "Ada Lovelace")
        self.assertIsNotNone(parsed.contact_phone)

    def test_an_order_without_them_is_still_valid(self) -> None:
        # The mobile client has not been updated, and every older order has
        # none. Requiring them here would break both.
        parsed = OrderCreateRequest(**order())
        self.assertIsNone(parsed.contact_name)
        self.assertIsNone(parsed.contact_phone)


class PhoneNumbersAreNormalisedTests(unittest.TestCase):
    def _phone(self, raw: str) -> str | None:
        return OrderCreateRequest(**order(contact_phone=raw)).contact_phone

    def test_the_same_number_typed_four_ways_stores_identically(self) -> None:
        for raw in ("(415) 555-0132", "415-555-0132", "415 555 0132", "+1 415 555 0132"):
            with self.subTest(raw=raw):
                self.assertEqual(self._phone(raw), "+14155550132")

    def test_a_bare_ten_digit_number_gets_the_default_country_code(self) -> None:
        # US is the default for this deployment; a customer typing their local
        # number should not have to know that.
        self.assertEqual(self._phone("4155550132"), "+14155550132")

    def test_a_number_that_already_has_a_country_code_is_left_alone(self) -> None:
        self.assertEqual(self._phone("+442071838750"), "+442071838750")

    def test_too_few_digits_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            self._phone("12345")

    def test_letters_are_refused(self) -> None:
        with self.assertRaises(ValidationError):
            self._phone("call-me-maybe")

    def test_an_empty_value_is_treated_as_not_given(self) -> None:
        # Blank is "the client sent nothing", not "the customer typed rubbish".
        self.assertIsNone(self._phone("   "))

    def test_a_name_of_whitespace_is_treated_as_not_given(self) -> None:
        self.assertIsNone(OrderCreateRequest(**order(contact_name="   ")).contact_name)


if __name__ == "__main__":
    unittest.main()
