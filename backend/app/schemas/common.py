"""Field types shared by several request schemas."""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator, Field


def _image_url(value: str | None) -> str | None:
    """https, or a path on this site - nothing a browser would run or leak.

    Image fields only had a length limit (2026-10-07 security review), so a
    `javascript:` or `data:` link, or a plain `http://` one that tracks who
    opens the storefront, could be saved and shown to every customer.
    """

    if value is None or value == "":
        return value
    if value.startswith("https://") or (value.startswith("/") and not value.startswith("//")):
        return value
    raise ValueError("An image link must start with https://")


#: An image link from a form: https or a site path, at most 500 characters.
ImageUrl = Annotated[str | None, Field(default=None, max_length=500), AfterValidator(_image_url)]
