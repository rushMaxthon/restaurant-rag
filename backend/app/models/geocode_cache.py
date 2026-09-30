from __future__ import annotations

import uuid

from sqlalchemy import Float, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GeocodeCache(TimestampMixin, Base):
    """One address, looked up once.

    A geocode result does not change, so every repeat lookup is a wasted call —
    a paid one with Google, and a step toward a block with Nominatim's usage
    policy, which requires caching outright. This table is how that requirement
    is met durably rather than only for as long as Redis happens to be up.

    `latitude` NULL is a REMEMBERED MISS, not an empty row. An address the
    geocoder could not place will not resolve on the next attempt either, and
    re-asking on every page load is how a quota disappears quietly. Only an
    actual "no match" is stored this way — a timeout or a rejected key is not a
    fact about the address and is never written here.
    """

    __tablename__ = "geocode_cache"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    #: Truncated SHA-256 of the normalised address text. Hashed rather than
    #: stored raw because the key is indexed and an address can be 300 chars.
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    #: The normalised text, for reading the table by eye when a quote looks
    #: wrong. Never matched against.
    query_text: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: `GeocodeConfidence`, as a string. Stored rather than recomputed because
    #: it decides whether a delivery may be priced from this point, and the
    #: provider's own reasoning is not available later.
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    #: The address as the provider understood it. The only way to spot the
    #: failure that matters: asking for a flat and being given a state
    #: centroid looks correct until you read this back.
    matched: Mapped[str] = mapped_column(String(500), nullable=False, default="")
