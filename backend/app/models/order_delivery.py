"""What a courier is doing with one order.

Kept beside the order rather than on it, for one reason that is worth stating
plainly: the courier's story and the restaurant's story are not the same
story, and forcing them into one column loses the part that costs money.

`Order.status` is the RESTAURANT's lifecycle and it is strictly linear —
PLACED, ACCEPTED, PREPARING, OUT_FOR_DELIVERY, DELIVERED, or CANCELLED. A
courier has outcomes that do not fit anywhere on that line: a rider collected
the food, could not hand it over, and brought it back. That is not CANCELLED
— nothing was called off, the food was cooked and is now spoiled — and it is
certainly not DELIVERED.

So the delivery keeps its own `state`, and only the states that genuinely
correspond move the order:

    IN_TRANSIT  -> OUT_FOR_DELIVERY
    DELIVERED   -> DELIVERED

FAILED moves nothing. The order stays where it was, the failure is visible
here, and somebody decides what to do about it — which is the honest shape,
because "who pays for a delivery that came back" is a commercial question and
not one a status machine should answer by itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from decimal import Decimal

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.order import Order


class OrderDelivery(TimestampMixin, Base):
    """One courier job, for one order."""

    __tablename__ = "order_deliveries"
    __table_args__ = (
        # The courier's id is how a webhook finds its way back to an order,
        # and it is looked up on every status push.
        Index("ix_order_deliveries_provider_order_id", "provider", "provider_order_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # One live delivery per order: unique, so a retried dispatch cannot put a
    # second rider on the same food. The dispatch path checks for the row
    # first, and this constraint is what makes that check safe under two
    # workers rather than merely likely to work.
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    #: Empty until the courier accepts it. A row with no id is a dispatch that
    #: was attempted and failed, which is worth keeping — it is the difference
    #: between "we never tried" and "they would not take it".
    provider_order_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    #: `DeliveryState`, stored as its string.
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    #: The courier's own word for it, unmapped. When a status nobody has seen
    #: before arrives, this is what makes it diagnosable without a replay.
    provider_status: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    rider_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    rider_mobile: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    tracking_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: Metres, as the courier measured it. The only distance figure this app
    #: has, and what a distance-based delivery fee would be priced from.
    distance_metres: Mapped[float | None] = mapped_column(Float, nullable=True)

    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Why a dispatch did not happen, when it did not. Read by the admin, so
    #: "no rider came" has an answer that is not "check the logs".
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    #: The courier's last payload, whole. Proof-of-delivery URLs, rider
    #: reassignments and timestamps live in shapes no interface should try to
    #: anticipate, and "what did they actually send" is otherwise unanswerable.
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- read out of `raw` so screens need not dig (migration 0081) --------
    pickup_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drop_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: What the courier invoices for the trip. The admin's figure, compared
    #: with the delivery fee the customer paid; not sent to anybody else.
    courier_charge: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    rider_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    rider_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    rider_location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    #: Every step the courier reported, oldest first. See `DeliveryResult`.
    timeline: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    #: Which booking this is: 1 for the first rider, 2 after a re-book. Sent
    #: to the courier inside the reference, which it requires to be unique.
    network_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    network_order_id: Mapped[str] = mapped_column(String(128), nullable=False, default="", server_default="")
    allocated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    order: Mapped["Order"] = relationship(back_populates="delivery")


__all__ = ["OrderDelivery"]
