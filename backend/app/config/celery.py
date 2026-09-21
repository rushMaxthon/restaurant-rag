from __future__ import annotations

import sys

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "restaurant_rag",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.ai_recommendations",
        "app.tasks.ai_offers",
        "app.tasks.embed",
        "app.tasks.generated_combos",
        "app.tasks.insights",
        "app.tasks.notifications",
        "app.tasks.payments",
        "app.tasks.whatsapp",
    ],
)

celery_app.conf.update(
    task_default_queue="default",
    task_routes={
        "app.tasks.ai_recommendations.generate_ai_recommendations_task": {"queue": "analytics"},
        "app.tasks.ai_offers.generate_ai_offers_task": {"queue": "analytics"},
        "app.tasks.embed.embed_menu_item": {"queue": "embeddings"},
        "app.tasks.generated_combos.rebuild_generated_combos_task": {"queue": "analytics"},
        "app.tasks.insights.generate_owner_briefings_task": {"queue": "analytics"},
        "app.tasks.insights.measure_action_outcomes_task": {"queue": "analytics"},
        "app.tasks.notifications.send_order_status_notification": {"queue": "notifications"},
        "app.tasks.whatsapp.answer_whatsapp_message": {"queue": "notifications"},
        "app.tasks.payments.reap_unpaid_orders_task": {"queue": "default"},
    },
    beat_schedule={
        # Abandoned card checkouts are cancelled a few minutes after their
        # intent TTL lapses, so they stop cluttering order history.
        "reap-unpaid-orders": {
            "task": "app.tasks.payments.reap_unpaid_orders_task",
            "schedule": crontab(minute="*/5"),
        },
        **(
            {
                "generate-ai-offers-daily": {
                    "task": "app.tasks.ai_offers.generate_ai_offers_task",
                    "schedule": crontab(
                        minute=settings.ai_offer_cron_minute,
                        hour=settings.ai_offer_cron_hour,
                    ),
                },
            }
            if settings.ai_offer_cron_enabled
            else {}
        ),
        # Runs well before service hours: narration is sequential against a
        # CPU-only model host, so a large tenant list takes real wall clock.
        **(
            {
                "generate-owner-briefings-daily": {
                    "task": "app.tasks.insights.generate_owner_briefings_task",
                    "schedule": crontab(
                        minute=settings.ai_manager_cron_minute,
                        hour=settings.ai_manager_cron_hour,
                    ),
                },
                # Runs an hour after generation, so a briefing and the outcomes
                # it might reference are never written in the same minute.
                "measure-action-outcomes-daily": {
                    "task": "app.tasks.insights.measure_action_outcomes_task",
                    "schedule": crontab(
                        minute=settings.ai_manager_cron_minute,
                        hour=(settings.ai_manager_cron_hour + 1) % 24,
                    ),
                },
            }
            if settings.ai_manager_cron_enabled
            else {}
        ),
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=settings.business_timezone,
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    # Windows cannot run the default prefork pool, and fails at it in the
    # worst possible way: SILENTLY, and only for the work.
    #
    # Measured on this machine, 2026-09-19. A customer's WhatsApp message
    # arrived, the webhook returned 200, the task was taken off the queue —
    # and no reply was ever sent. `inspect.ping` answered, `active_queues`
    # looked right, the queue was empty and the worker reported itself idle.
    # Every check said healthy. The pool's child processes were crash-looping
    # on `PermissionError: [WinError 5] Access is denied` out of
    # `billiard/synchronize.py`, which is that library's cross-process
    # semaphore being refused by the OS: the parent kept acking messages and
    # no child could ever receive one. With the worker started detached and
    # no logfile, the traceback went nowhere at all.
    #
    # `solo` runs tasks in the main process — no children, no semaphore, no
    # loss. It is single-concurrency, which is right for a dev box and wrong
    # for production, so this is scoped to Windows. Docker and Render are
    # Linux and keep prefork.
    **({"worker_pool": "solo"} if sys.platform == "win32" else {}),
)

@worker_ready.connect
def _warm_models(**_kwargs: object) -> None:
    """Load the models once this worker is actually able to run tasks.

    The worker is where WhatsApp is answered, and WhatsApp is where the cost
    showed up: a turn that took 54 seconds against a 30-second budget, nearly
    all of it a cold qwen3:8b, and a wrong answer at the end of it because the
    budget had gone. Nothing warmed the generation model in any process.

    Imported inside the handler, not at module scope. This module is imported
    by `app.main` and by every `celery` command including `inspect` and `beat`;
    pulling the service layer in at import time would make all of them pay for
    it, and would give this file a dependency it has no other use for.

    `worker_ready` rather than `worker_init`, so nothing is warmed by a process
    that turned out not to be able to serve.
    """

    from app.services.model_warmup import start_model_warm_up

    start_model_warm_up(name="model-warmup-worker")


__all__ = ["celery_app"]
