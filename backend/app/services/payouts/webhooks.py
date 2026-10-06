"""Route's own events, from the platform webhook.

The same rule as the delivery webhook: an event is a nudge. A transfer event
queues a fetch of the transfer, and the row is moved by what Razorpay says
when asked, never by the body. An account event is the exception, because
the activation status IS the fact and fetching it would return the same
word. It is still applied only to an account id this database already holds.

`settlement.processed` carries a settlement rather than a transfer, so it is
not matched here; the transfer's own event and the hourly sweep record the
settlement instead.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PayoutAccountStatus
from app.models.restaurant_payout import RestaurantPayoutAccount
from app.services.payouts.route_client import ACCOUNT_STATUS_FOR_ACTIVATION

logger = logging.getLogger(__name__)


def after_commit_task(db: Session, task: str, **kwargs: str) -> None:
    """Queue a Celery task once `db` commits; a rollback first discards it.

    `after_soft_rollback`, for the reason `realtime/outbox.py` gives: a
    listener left behind by a rolled-back write would otherwise go out with
    the session's NEXT commit, and a reversal for a cancellation that never
    happened claws back a restaurant's share for a live order. Never raises.
    """

    live = {"queued": True}
    # Tie the queue to a transaction, as the outbox does: with none begun,
    # `rollback()` fires no event while `commit()` autobegins and fires
    # `after_commit`, so the step would survive the rollback that disowned
    # it. Beginning issues no SQL.
    if not db.in_transaction():
        db.begin()

    def _discard(_session: Session, _previous: object) -> None:
        live["queued"] = False

    def _send(_session: Session) -> None:
        if not live["queued"]:
            return
        try:
            from app.config.celery import celery_app

            celery_app.send_task(task, kwargs=kwargs)
        except Exception:  # noqa: BLE001
            logger.warning("Could not queue %s", task, exc_info=True)

    sa_event.listen(db, "after_soft_rollback", _discard, once=True)
    sa_event.listen(db, "after_commit", _send, once=True)


def handle_route_event(db: Session, body: dict[str, Any]) -> None:
    name = str(body.get("event") or "")
    entities = body.get("payload") or {}
    if name.startswith("transfer."):
        transfer = (entities.get("transfer") or {}).get("entity") or {}
        if transfer.get("id"):
            after_commit_task(db, "app.tasks.payouts.refresh_transfer_task", transfer_id=str(transfer["id"]))
            db.commit()
        return
    if name.startswith("product.route.") or name.startswith("account."):
        account_id = str(body.get("account_id") or "")
        product = (entities.get("merchant_product") or {}).get("entity") or {}
        status = ACCOUNT_STATUS_FOR_ACTIVATION.get(str(product.get("activation_status") or ""))
        if not account_id or status is None:
            return
        account = db.scalar(
            select(RestaurantPayoutAccount).where(RestaurantPayoutAccount.razorpay_account_id == account_id)
        )
        if account is None:
            return
        became_active = status == PayoutAccountStatus.ACTIVE and account.status != status.value
        account.status = status.value
        if became_active:
            after_commit_task(db, "app.tasks.payouts.flush_waiting_task", restaurant_id=str(account.restaurant_id))
        db.commit()
