from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from app.config import get_settings
from app.config.celery import celery_app
from app.models.enums import OrderStatus

settings = get_settings()
logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.notifications.send_order_status_notification",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def send_order_status_notification(
    self: Any,
    *,
    order_id: str,
    customer_id: str,
    restaurant_id: str,
    new_status: str,
) -> dict[str, str]:
    order_uuid = str(uuid.UUID(order_id))
    customer_uuid = str(uuid.UUID(customer_id))
    restaurant_uuid = str(uuid.UUID(restaurant_id))
    normalized_status = OrderStatus(new_status).value

    payload = {
        "order_id": order_uuid,
        "customer_id": customer_uuid,
        "restaurant_id": restaurant_uuid,
        "status": normalized_status,
        "title": "Order update",
        "body": f"Your order is now {normalized_status.replace('_', ' ').title()}",
    }

    credentials_present = os.path.exists(settings.fcm_credentials_path)
    if credentials_present:
        logger.info(
            "Prepared FCM notification payload for order %s using credentials at %s",
            order_uuid,
            settings.fcm_credentials_path,
        )
    else:
        logger.info(
            "FCM credentials not found at %s. Emitting mock notification payload for order %s",
            settings.fcm_credentials_path,
            order_uuid,
        )

    logger.info("Order status notification payload: %s", payload)
    return {"status": "queued", "order_id": order_uuid, "new_status": normalized_status}
