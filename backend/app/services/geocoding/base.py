"""Turning an address into a point, behind one contract.

The same arrangement `payments/base.py` and `delivery/base.py` use, for the
same reason: everything above is written against these types, so a second
geocoder is a module and a registry entry rather than a change to the
checkout.

A geocoder is unlike the other two integrations in one way that shapes this
whole package. A payment either happens or it does not, and a courier either
accepts the job or refuses it. A geocoder ALWAYS answers something. Ask it for
"12 Fake Street, Nowhere" and it will cheerfully return the centroid of the
nearest city, or of the country, with no error and no complaint — and a
delivery priced from a country centroid is a real number for a trip nobody is
taking.

So `GeocodedPoint` carries `confidence` and `matched`, and callers are expected
to look at them. Every field here exists to answer "should this point be
trusted with somebody's money", because the one thing a geocoder cannot be
relied on to do is say no.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class GeocodeConfidence(StrEnum):
    """How precisely the answer names the place that was asked for.

    Collapsed from every provider's own vocabulary, which none of them agree
    on: Nominatim has thirty-odd `type` values, Google has `location_type` plus
    an `address_components` tree, Mapbox has `place_type` plus a relevance
    score. Mapping them one-for-one would put one provider's model in the
    checkout.

    The boundary that matters is `ROOFTOP`/`STREET` against everything below.
    A street-level point prices a real trip. A `LOCALITY` point prices the
    middle of a city, which for a courier quote is a plausible-looking number
    about nowhere.
    """

    #: The building itself.
    ROOFTOP = "ROOFTOP"
    #: The street, or an interpolated position along it. Good enough to price.
    STREET = "STREET"
    #: A postcode's area. In India a PIN code can span kilometres, so this is
    #: a real answer and a poor one.
    POSTCODE = "POSTCODE"
    #: A neighbourhood, suburb or city. Not a delivery address.
    LOCALITY = "LOCALITY"
    #: A region, state or country. Never price from this.
    REGION = "REGION"

    @property
    def is_precise(self) -> bool:
        """Whether a delivery may be priced from this point.

        The line is drawn here, once, rather than at each call site, because
        "is this good enough to charge somebody for" is one decision and three
        copies of it would drift.
        """

        return self in {GeocodeConfidence.ROOFTOP, GeocodeConfidence.STREET}


@dataclass(slots=True)
class GeocodedPoint:
    """Where an address is, and how much that claim is worth.

    `matched` is the address as the PROVIDER understood it, kept because it is
    the only way to see the failure mode that matters: asking for a flat in
    Bodakdev and being handed the centroid of Gujarat looks identical to a
    correct answer until you read it back.
    """

    latitude: float
    longitude: float
    confidence: GeocodeConfidence
    #: What the provider thinks it found. Shown in the admin, logged on a
    #: refusal, and never parsed.
    matched: str = ""
    #: Which geocoder answered, so a bad coordinate can be traced to it.
    provider: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_precise(self) -> bool:
        return self.confidence.is_precise


class GeocodingError(RuntimeError):
    """A geocoder call failed in a way worth surfacing.

    `retryable` separates "their service blinked" from "this address will
    never resolve". Nothing retries in a loop here — a checkout cannot wait —
    but the distinction decides whether a negative result is worth caching,
    and caching a transport failure would pin a good address to "unknown" for
    as long as the cache lives.
    """

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True)
class AddressQuery:
    """An address to look up, structured where possible.

    Structured beats a single blob and it is not a close call. A geocoder given
    `line1 + city + state + postcode + country` as separate fields can refuse
    a house number in the wrong city; given one string it will silently pick
    whichever interpretation scores best. Our checkout collects these as
    separate boxes already, so throwing that structure away to build a
    one-line string and asking a geocoder to take it apart again is a loss for
    no reason.

    `freeform` is the fallback for addresses that were only ever stored as one
    block — every order placed before this existed.
    """

    line1: str = ""
    line2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = ""
    freeform: str = ""

    @property
    def is_empty(self) -> bool:
        return not any(
            part.strip()
            for part in (
                self.line1,
                self.line2,
                self.city,
                self.state,
                self.postal_code,
                self.freeform,
            )
        )

    def as_text(self) -> str:
        """One line, for providers that only take one.

        The country goes last and the postcode just before it, which is the
        order every provider's parser expects and the order a postal service
        would read.
        """

        if self.freeform.strip() and not self.line1.strip():
            return " ".join(self.freeform.split())
        parts = [
            self.line1,
            self.line2,
            self.city,
            self.state,
            self.postal_code,
            self.country,
        ]
        return ", ".join(" ".join(p.split()) for p in parts if p and p.strip())

    def cache_key(self) -> str:
        """A stable identity for this address, for caching.

        Case and whitespace are normalised so "12 MG Road" and "12  mg  road"
        are one cache entry rather than two lookups and two paid calls.
        """

        return " ".join(self.as_text().lower().split())


@runtime_checkable
class Geocoder(Protocol):
    """What every geocoder must do."""

    name: str

    def is_configured(self) -> bool:
        """Whether this geocoder has what it needs to be called at all."""
        ...

    def geocode(self, query: AddressQuery, *, timeout: float | None = None) -> GeocodedPoint | None:
        """Where that address is, or None if nothing was found.

        None means "no match", which is an answer. A failure to ASK raises
        `GeocodingError` — the two must not be confused, because one is worth
        remembering and the other is worth forgetting.
        """
        ...


__all__ = [
    "AddressQuery",
    "GeocodeConfidence",
    "GeocodedPoint",
    "Geocoder",
    "GeocodingError",
]
