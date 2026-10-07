"""An image link an owner saves must be https, or a path on this site.

Found in the 2026-10-07 security review: menu, logo and cover image fields
only had a length limit, so `javascript:...`, `data:...` or a plain `http://`
link (mixed content, and a way to watch who opens the storefront) could be
saved and then rendered on every customer's screen. Every link stored today
is https or a site path (checked on Supabase), so nothing existing breaks.
"""

from __future__ import annotations

import os
import sys
import unittest

from pydantic import BaseModel, ValidationError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.schemas.common import ImageUrl  # noqa: E402


class _Form(BaseModel):
    image_url: ImageUrl = None


class WhatIsSaved(unittest.TestCase):
    def test_https_and_site_paths(self) -> None:
        for url in ("https://cdn.example/a.jpg", "/images/dish.png", None, ""):
            with self.subTest(url=url):
                _Form(image_url=url)

    def test_everything_else_is_refused(self) -> None:
        for url in (
            "javascript:alert(1)",
            "data:image/svg+xml;base64,PHN2Zz4=",
            "http://cdn.example/a.jpg",
            "//evil.example/a.jpg",
            "ftp://x/a.jpg",
            " javascript:alert(1)",
        ):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                _Form(image_url=url)

    def test_the_real_forms_use_it(self) -> None:
        from app.schemas.menu_item import MenuItemRequestBase
        from app.schemas.restaurant import RestaurantBase

        from pydantic import AfterValidator

        from app.schemas.common import _image_url

        fields = [
            MenuItemRequestBase.model_fields["image_url"],
            RestaurantBase.model_fields["logo_image_url"],
            RestaurantBase.model_fields["cover_image_url"],
        ]
        for field in fields:
            validators = [m.func for m in field.metadata if isinstance(m, AfterValidator)]
            self.assertIn(_image_url, validators)


if __name__ == "__main__":
    unittest.main()
