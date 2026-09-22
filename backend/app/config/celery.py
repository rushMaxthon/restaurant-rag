from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

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
        "app.tasks.marketing",
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
        # Same queue as the order push: both talk to Firebase, and a campaign
        # send must queue behind order notifications rather than compete with
        # them for a separate worker's attention.
        "app.tasks.marketing.send_marketing_campaign": {"queue": "notifications"},
        "app.tasks.marketing.run_due_marketing_campaigns": {"queue": "notifications"},
        # Analytics, not delivery: this only reads numbers back from Meta, and
        # putting it on the notifications queue would let a slow Graph API
        # call sit in front of an order push.
        "app.tasks.marketing.refresh_social_insights": {"queue": "analytics"},
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
        # Scheduled campaigns are picked up on an interval rather than at an
        # exact instant, which is why quiet hours and reach are re-checked when
        # the send fires instead of being trusted from when it was scheduled.
        # Unconditional: the schedule only finds campaigns an owner explicitly
        # scheduled, and `enable_marketing_dispatch` still decides whether
        # anything leaves the building.
        "run-due-marketing-campaigns": {
            "task": "app.tasks.marketing.run_due_marketing_campaigns",
            "schedule": crontab(
                minute=f"*/{max(1, settings.marketing_scheduler_interval_minutes)}"
            ),
        },
        # A published post has no delivery callback — it just accumulates
        # impressions that nothing tells us about — so its numbers are polled.
        # Hourly, because they move for days and then stop, and an owner
        # reading a figure an hour stale is far better served than one
        # reading no figure at all.
        "refresh-social-insights": {
            "task": "app.tasks.marketing.refresh_social_insights",
            "schedule": crontab(minute="7"),
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
)

__all__ = ["celery_app"]
