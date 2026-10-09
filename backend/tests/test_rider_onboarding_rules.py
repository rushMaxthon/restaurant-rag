"""The rules a rider's application is checked against, with no database.

Pure functions, mirrored in the rider app (`rider/src/utils/onboarding.ts`)
so the phone says "that IFSC is wrong" before a request is made - but the
server's copy here is the rule.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models.enums import ApplicationItemKind, VehicleType  # noqa: E402
from app.services.fleet.onboarding.rules import (  # noqa: E402
    clean_plate,
    is_adult,
    licence_valid,
    required_items,
    valid_account,
    valid_ifsc,
    valid_pan,
    valid_pincode,
    valid_upi,
)


class RequiredItems(unittest.TestCase):
    def test_a_motorbike_needs_licence_and_rc(self) -> None:
        items = required_items(VehicleType.BIKE)
        for kind in ("RC", "LICENCE_FRONT", "LICENCE_BACK", "VEHICLE_DETAILS"):
            self.assertIn(ApplicationItemKind(kind), items)

    def test_a_bicycle_needs_no_licence_or_rc(self) -> None:
        items = required_items(VehicleType.CYCLE)
        for kind in ("RC", "LICENCE_FRONT", "LICENCE_BACK"):
            self.assertNotIn(ApplicationItemKind(kind), items)

    def test_a_low_speed_ev_needs_neither(self) -> None:
        self.assertNotIn(ApplicationItemKind.RC, required_items(VehicleType.EV_SCOOTER))
        self.assertNotIn(ApplicationItemKind.LICENCE_FRONT, required_items(VehicleType.EV_SCOOTER))

    def test_everyone_needs_identity_and_bank(self) -> None:
        for vehicle in VehicleType:
            items = required_items(vehicle)
            for kind in ("PERSONAL", "SELFIE", "AADHAAR_FRONT", "AADHAAR_BACK", "PAN", "BANK_DETAILS"):
                self.assertIn(ApplicationItemKind(kind), items)

    def test_no_vehicle_chosen_yet_still_lists_the_basics(self) -> None:
        self.assertIn(ApplicationItemKind.PERSONAL, required_items(None))

    def test_the_vehicle_is_always_asked_for(self) -> None:
        # Every rider rides something: a bicycle rider who never picked one
        # could submit without saying what they deliver on.
        for vehicle in (None, *VehicleType):
            self.assertIn(ApplicationItemKind.VEHICLE_DETAILS, required_items(vehicle))


class Validators(unittest.TestCase):
    def test_plates_are_normalised(self) -> None:
        self.assertEqual(clean_plate(" gj 05 ab 1234 "), "GJ05AB1234")
        self.assertEqual(clean_plate("GJ-5-1234"), "GJ51234")
        self.assertEqual(clean_plate("22 BH 1234 AA"), "22BH1234AA")
        self.assertIsNone(clean_plate("hello"))

    def test_pan_ifsc_pincode(self) -> None:
        self.assertEqual(valid_pan("abcde1234f"), "ABCDE1234F")
        self.assertIsNone(valid_pan("ABCDE12345"))
        self.assertEqual(valid_ifsc("sbin0001234"), "SBIN0001234")
        self.assertIsNone(valid_ifsc("SBIN1001234"))
        self.assertEqual(valid_pincode("395009"), "395009")
        self.assertIsNone(valid_pincode("095009"))

    def test_account_numbers_must_match(self) -> None:
        self.assertEqual(valid_account("1234 5678 9012", "123456789012"), "123456789012")
        self.assertIsNone(valid_account("123456789012", "123456789013"))
        self.assertIsNone(valid_account("12345", "12345"))

    def test_eighteen_on_the_day(self) -> None:
        today = date(2026, 10, 9)
        self.assertTrue(is_adult(date(2008, 10, 9), today))
        self.assertFalse(is_adult(date(2008, 10, 10), today))

    def test_born_on_the_29th_of_february(self) -> None:
        self.assertFalse(is_adult(date(2008, 2, 29), date(2026, 2, 28)))
        self.assertTrue(is_adult(date(2008, 2, 29), date(2026, 3, 1)))

    def test_an_expired_licence(self) -> None:
        self.assertFalse(licence_valid(date(2026, 10, 8), date(2026, 10, 9)))
        self.assertTrue(licence_valid(date(2026, 10, 10), date(2026, 10, 9)))

    def test_upi(self) -> None:
        self.assertEqual(valid_upi("Ravi.k@okaxis"), "ravi.k@okaxis")
        self.assertIsNone(valid_upi("ravi"))



class ImageChecks(unittest.TestCase):
    """A photo's type comes from its first bytes, never from its name: a PDF
    or a web page renamed to .jpg must not reach an admin's browser."""

    def test_types_come_from_the_bytes_not_the_name(self) -> None:
        from app.services.fleet.onboarding.storage import sniff_image

        self.assertEqual(sniff_image(b"\xff\xd8\xff\xe0rest"), "image/jpeg")
        self.assertEqual(sniff_image(b"\x89PNG\r\n\x1a\nrest"), "image/png")
        self.assertEqual(sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "image/webp")
        self.assertIsNone(sniff_image(b"%PDF-1.7"))
        self.assertIsNone(sniff_image(b"<html>"))


class StorageClient(unittest.TestCase):
    """Supabase Storage over its REST API. The bucket is created on the first
    upload that finds it missing, private, so nobody has to click it into
    existence in a dashboard."""

    def test_the_bucket_is_made_private_on_first_use(self) -> None:
        import httpx

        from app.services.fleet.onboarding import storage

        calls: list[tuple[str, str]] = []
        state = {"bucket": False}

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            if request.url.path == "/storage/v1/bucket":
                state["bucket"] = True
                self.assertIn(b'"public": false', request.content.replace(b'"public":false', b'"public": false'))
                return httpx.Response(200, json={"name": "rider-documents"})
            if not state["bucket"]:
                return httpx.Response(404, json={"statusCode": "404", "error": "Bucket not found"})
            return httpx.Response(200, json={"Key": "rider-documents/x"})

        client = storage.StorageClient("https://x.supabase.co", "key", "rider-documents", httpx.MockTransport(handler))
        client.upload("riders/u/SELFIE-1.jpg", b"\xff\xd8\xff", "image/jpeg")
        self.assertEqual(
            [c[0] for c in calls], ["POST", "POST", "POST"], "upload, create bucket, upload again"
        )
        self.assertEqual(calls[1], ("POST", "/storage/v1/bucket"))

    def test_a_signed_link_is_absolute(self) -> None:
        import httpx

        from app.services.fleet.onboarding import storage

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"signedURL": "/object/sign/rider-documents/a.jpg?token=t"})

        client = storage.StorageClient("https://x.supabase.co", "key", "rider-documents", httpx.MockTransport(handler))
        self.assertEqual(
            client.signed_url("a.jpg"), "https://x.supabase.co/storage/v1/object/sign/rider-documents/a.jpg?token=t"
        )



class UploadDoesNotStallTheServer(unittest.TestCase):
    """Socket.IO lives inside the same ASGI app, so an `async` route that does
    a blocking upload stalls every kitchen board and rider on the worker for
    its whole length. The route must be a plain function (run in a thread),
    and the storage client one shared, reused connection pool."""

    def test_the_upload_route_runs_in_a_thread(self) -> None:
        import inspect

        from app.api.rider_signup import upload_item

        self.assertFalse(inspect.iscoroutinefunction(upload_item))

    def test_one_storage_client_is_reused(self) -> None:
        from unittest import mock

        from app.services.fleet.onboarding import storage

        storage.reset_client()
        self.addCleanup(storage.reset_client)
        with mock.patch.object(storage, "configured", return_value=True):
            self.assertIs(storage.client(), storage.client())


if __name__ == "__main__":
    unittest.main()
