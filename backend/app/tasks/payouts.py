"""Payout steps, run after the order's own transaction has committed.

A retryable Razorpay error (network, 5xx) is retried a few times with
backoff; a refusal is written onto the row as FAILED by the service and not
retried here. The hourly sweep is the backstop for both.
"""

from __future__ import annotations

import uuid

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.payments.base import PaymentProviderError
from app.services.payouts import service

_RETRY = dict(autoretry_for=(PaymentProviderError,), retry_backoff=30, retry_kwargs={"max_retries": 3})


@celery_app.task(name="app.tasks.payouts.transfer_payout_task", **_RETRY)
def transfer_payout_task(order_id: str) -> str:
    with SessionLocal() as db:
        row = service.transfer(db, uuid.UUID(order_id))
        return row.status if row else "missing"


@celery_app.task(name="app.tasks.payouts.release_payout_task", **_RETRY)
def release_payout_task(order_id: str) -> str:
    with SessionLocal() as db:
        row = service.release(db, uuid.UUID(order_id))
        return row.status if row else "missing"


@celery_app.task(name="app.tasks.payouts.reverse_payout_task", **_RETRY)
def reverse_payout_task(order_id: str) -> str:
    with SessionLocal() as db:
        row = service.reverse(db, uuid.UUID(order_id))
        return row.status if row else "missing"


@celery_app.task(name="app.tasks.payouts.refresh_transfer_task")
def refresh_transfer_task(transfer_id: str) -> str:
    with SessionLocal() as db:
        row = service.refresh_transfer(db, transfer_id)
        return row.status if row else "missing"


@celery_app.task(name="app.tasks.payouts.flush_waiting_task")
def flush_waiting_task(restaurant_id: str) -> int:
    with SessionLocal() as db:
        return service.flush_waiting(db, uuid.UUID(restaurant_id))


@celery_app.task(name="app.tasks.payouts.retry_payouts_task")
def retry_payouts_task() -> int:
    with SessionLocal() as db:
        return service.retry_stuck(db)
