"""Where a restaurant actually is, and how to reach it.

A storefront needs this in three places that all have to agree — the footer on
every page, a contact page, and the `LocalBusiness` structured data a search
engine reads — so it is resolved once here rather than assembled three times.

**The columns have always been there; nothing exposed them.** `restaurants`
carries a full postal address and a phone number, and `/app-config` sent
neither, so the storefront had no honest way to say where the kitchen is. The
footer that prompted this was the forcing function: a brand site with no
address reads as a storefront nobody stands behind.

**A placeholder is an absence, and is returned as one.** Onboarding asks for a
name and an owner, not an address, so those NOT NULL columns carry
`PLACEHOLDER_ADDRESS`, `PLACEHOLDER_CITY`, `PLACEHOLDER_STATE` and
`PLACEHOLDER_POSTAL_CODE` from the moment a tenant is created. Passing them
through would print "Pending restaurant setup, Pending 000000" in the footer of
a live website — worse than printing nothing, because nothing is at least not a
claim. So every key here is omitted when it has not really been filled in, and
the client renders what it is given.

That is also why `address` is assembled HERE rather than client-side. Which
parts exist varies per tenant, and a comma-joined list with holes in it is the
kind of thing two clients format differently — one printing "Ahmedabad, ,
380015". One function, one answer.
"""

from __future__ import annotations

from app.models.restaurant import (
    PLACEHOLDER_ADDRESS,
    PLACEHOLDER_CITY,
    PLACEHOLDER_POSTAL_CODE,
    PLACEHOLDER_STATE,
    Restaurant,
)

ADDRESS_LINE_1_KEY = "address_line_1"
ADDRESS_LINE_2_KEY = "address_line_2"
CITY_KEY = "city"
STATE_KEY = "state"
POSTAL_CODE_KEY = "postal_code"
COUNTRY_KEY = "country"
PHONE_KEY = "phone"
ADDRESS_KEY = "address"

CONTACT_KEYS = (
    ADDRESS_LINE_1_KEY,
    ADDRESS_LINE_2_KEY,
    CITY_KEY,
    STATE_KEY,
    POSTAL_CODE_KEY,
    COUNTRY_KEY,
    PHONE_KEY,
    ADDRESS_KEY,
)

# Each column's own "not filled in yet" value. `address_line_2`, `country` and
# `phone_number` are absent from this map on purpose: the first two are
# genuinely nullable or defaulted, and a phone number has no placeholder.
_PLACEHOLDERS = {
    ADDRESS_LINE_1_KEY: PLACEHOLDER_ADDRESS,
    CITY_KEY: PLACEHOLDER_CITY,
    STATE_KEY: PLACEHOLDER_STATE,
    POSTAL_CODE_KEY: PLACEHOLDER_POSTAL_CODE,
}


def _real(value: str | None, *, key: str) -> str:
    """One column, or "" when it is blank or still the onboarding placeholder."""

    collapsed = " ".join((value or "").split())
    if not collapsed:
        return ""
    if collapsed == _PLACEHOLDERS.get(key):
        return ""
    return collapsed


def read_contact(restaurant: Restaurant) -> dict[str, str]:
    """This restaurant's real contact details, with the unfilled keys omitted.

    An empty dict is a correct and common answer — it means nobody has
    completed this tenant's address yet, and every surface that reads this is
    built to show nothing rather than show "Pending".
    """

    parts = {
        ADDRESS_LINE_1_KEY: _real(restaurant.address_line_1, key=ADDRESS_LINE_1_KEY),
        ADDRESS_LINE_2_KEY: _real(restaurant.address_line_2, key=ADDRESS_LINE_2_KEY),
        CITY_KEY: _real(restaurant.city, key=CITY_KEY),
        STATE_KEY: _real(restaurant.state, key=STATE_KEY),
        POSTAL_CODE_KEY: _real(restaurant.postal_code, key=POSTAL_CODE_KEY),
        COUNTRY_KEY: _real(restaurant.country, key=COUNTRY_KEY),
        PHONE_KEY: _real(restaurant.phone_number, key=PHONE_KEY),
    }

    # Street, city and state read as one line; the postal code rides with the
    # state the way an envelope is addressed. The country is deliberately left
    # out of the single line — a customer ordering delivery knows which country
    # they are in, and it is the part that reads as filler.
    street = ", ".join(
        value
        for value in (
            parts[ADDRESS_LINE_1_KEY],
            parts[ADDRESS_LINE_2_KEY],
            parts[CITY_KEY],
        )
        if value
    )
    tail = " ".join(value for value in (parts[STATE_KEY], parts[POSTAL_CODE_KEY]) if value)
    parts[ADDRESS_KEY] = ", ".join(value for value in (street, tail) if value)

    return {key: value for key, value in parts.items() if value}


__all__ = ["CONTACT_KEYS", "read_contact"]
