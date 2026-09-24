from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import re

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Hosts that mean "an Ollama running alongside this deployment" — loopback, the
# compose service name, and the Docker Desktop bridge back to the macOS host.
# Anything else is treated as remote, which is what decides whether local-only
# request options like `keep_alive` are worth sending.
_LOCAL_OLLAMA_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "0.0.0.0", "ollama", "host.docker.internal"}
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Restaurant RAG API"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = True
    api_v1_prefix: str = "/api"
    business_timezone: str = "Asia/Kolkata"
    # Dialling code assumed when a customer types a bare local number at
    # checkout. Settable per deployment for the same reason the timezone is:
    # nothing here should hardcode one country.
    #
    # It said "+1" while `business_timezone` above said Asia/Kolkata, and
    # these two cannot disagree: a Surat customer typing their real mobile,
    # 9825012345, had it stored as +19825012345 — a United States number, on
    # every order they ever placed, with the checkout showing them "+1" as
    # confirmation. India is +91 and its mobile numbers are 10 digits, so the
    # digit count below is already right.
    default_phone_country_code: str = "+91"
    # How many digits a local number has once the country code is stripped.
    # US and Canada are 10; a deployment elsewhere changes this rather than
    # editing a validator.
    default_phone_national_digits: int = 10
    # App client that owns customers who arrive without a bundle id
    # (the customer web app), and the fallback identity scope.
    default_app_client_key: str = "marketplace"

    # 5173 customer web, 5174 the admin/owner panel, 5175 the kitchen board.
    # Each dev server pins its own port (`strictPort`) so this list stays true
    # rather than drifting the first time one of them is already in use.
    backend_cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://localhost:5174,http://localhost:5175,http://localhost:8080,http://localhost:8081"
    )

    # A phone or a second laptop on the same wifi reaches the dev servers by this
    # machine's LAN address, not `localhost`, so every such origin is a CORS
    # miss against the list above — and the address is DHCP-assigned, so pinning
    # it in the list means re-editing .env whenever the lease changes. A regex
    # covers the whole private range instead. Empty by default: this exists for
    # local device testing, and production must keep naming its origins exactly.
    backend_cors_origin_regex: str = ""

    # A managed provider hands out ONE connection string rather than the five
    # discrete parts below — Render injects `DATABASE_URL` from the database it
    # provisions, and its host, password and database name are all generated, so
    # they cannot be written into a compose file ahead of time. When this is set
    # it wins over POSTGRES_*, which lets the same image run unchanged on Render
    # and under docker compose. Empty (the compose case) composes the URL from
    # the parts, exactly as before.
    database_url: str = ""
    postgres_server: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "postgres"
    postgres_password: str = "postgres"
    postgres_db: str = "restaurant_rag"
    database_echo: bool = False
    # Connection pool, per process. The total a deployment opens is
    #   (gunicorn workers + celery child processes) x (pool_size + max_overflow)
    # which must stay under the server's `max_connections`. Left at SQLAlchemy's
    # defaults (5 + 10) a four-worker API plus nine Celery children can ask for
    # 210 connections against a stock limit of 100, which surfaces as
    # intermittent "sorry, too many clients already" rather than a clean failure.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    # Recycle below any idle timeout enforced by a proxy or managed Postgres, so
    # a connection is never handed out after the server has already dropped it.
    db_pool_recycle: int = 1800
    # How long a request waits for a free connection before failing. Kept short:
    # a request queueing 30s for a connection has already lost.
    db_pool_timeout: int = 30

    jwt_secret_key: str = "change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440

    # Where GENERATION goes. Either a local Ollama or Ollama Cloud
    # (https://ollama.com), which needs `ollama_api_key` below.
    ollama_base_url: str = "http://localhost:11434"
    # Where EMBEDDINGS go, when that differs from generation.
    #
    # It has to be separable, because Ollama Cloud serves no embedding route at
    # all: /api/embed answers 401 for every model with or without a key, and
    # /api/embeddings and /v1/embeddings both answer 404, while /api/generate
    # with the same key answers 200. Menu embeddings and customer RAG retrieval
    # therefore stay on a local Ollama even when generation is in the cloud.
    #
    # Empty means "same host as generation", so an all-local deployment is
    # unaffected and needs no new configuration.
    ollama_embedding_base_url: str = ""
    # Bearer token for Ollama Cloud. Empty for a local Ollama, which needs none.
    #
    # Sent ONLY to `ollama_base_url`. If embeddings point somewhere else, that
    # host does not receive this key — a credential issued for one service must
    # not be handed to another.
    ollama_api_key: str = ""
    # How much hidden reasoning the generation model may produce.
    #
    # This is the single setting that makes a reasoning model usable here, and it
    # is per-deployment because models disagree about it:
    #
    #   "false"  qwen3:8b — discards its reasoning, so producing it is pure waste
    #   "low"    gpt-oss  — IGNORES think:false and reasons anyway. Its reasoning
    #                       counts against num_predict, so at this app's budgets
    #                       the whole budget went to thinking and `response` came
    #                       back EMPTY: measured 0/3 usable on the planner, 0/2 on
    #                       the narrator, 0/4 on chat answers. At "low" the
    #                       reasoning drops from ~1150 to ~40-143 characters and
    #                       every path fits inside its existing budget.
    #
    # "medium"/"high" are accepted by the API and measured NOT to fit: both still
    # exhaust a 300-token budget on reasoning alone.
    ollama_think_mode: str = "false"
    ollama_chat_model: str = "qwen3:8b"
    ollama_embedding_model: str = "nomic-embed-text"

    # --- embeddings ---------------------------------------------------------
    #
    # Which provider turns text into vectors. "ollama" (local development,
    # nomic-embed-text) or "gemini" (production, Gemini Embedding 2). Generation
    # is configured entirely separately: a deployment can run cloud generation
    # and local embeddings, or neither, or both.
    embedding_provider: str = "ollama"
    # Fixed at 768 to match the `Vector(768)` column on `menu_embeddings`.
    # nomic-embed-text is natively 768; Gemini truncates to it via Matryoshka.
    # Changing this REQUIRES a schema migration and a full re-embed, so it is a
    # setting only so the two providers can be checked against one number.
    embedding_dimensions: int = 768
    # Vectors from different models are not comparable even at the same
    # dimension, so a provider switch invalidates every stored vector. The
    # backfill refuses to run when this signature changes, unless forced.
    gemini_api_key: str = ""
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_embedding_timeout_seconds: float = 20.0
    ollama_timeout_seconds: float = 120.0
    # Read timeout for chat generation. Sized for a CPU-only host: a cold
    # prompt-eval alone can take 20-30s before the first token is produced.
    ollama_chat_timeout_seconds: float = 90.0
    # Sized for a COLD load, not a warm call. Warm, nomic-embed-text answers in
    # ~0.05s; when it has been evicted and qwen3:8b holds memory, the reload
    # measured 23.0s on the reference CPU-only host. The previous 20.0 cleared
    # the warm path and nothing else, so the first query after any idle period
    # timed out — and `_embed_query` returns None rather than raising, so that
    # query silently dropped to the keyword tier with no error anywhere.
    # Flaky-looking, never flaky: it failed exactly once per eviction.
    ollama_embedding_timeout_seconds: float = 60.0
    # Long enough that an idle owner does not pay a 14-second model reload on
    # their next question. The answer model, the planner and the narrator all
    # deliberately name the SAME model: two different ones evict each other on
    # every turn, which costs that reload twice per question.
    ollama_keep_alive: str = "60m"
    # Sized so a dish search can surface every distinct matching dish once
    # branch-level duplicates are collapsed (each branch stores its own copy
    # of a dish, so raw retrieval needs headroom above the suggestion count).
    rag_top_k_results: int = 8
    rag_history_messages: int = 6
    rag_suggestion_limit: int = 6
    rag_max_context_candidates: int = 6
    rag_max_description_chars: int = 120
    rag_max_reply_tokens: int = 120

    redis_url: str = "redis://localhost:6379/0"
    # How long a cache call may spend trying to reach Redis before it gives up
    # and reports a miss. Every call site already treats a `RedisError` as a
    # miss, so an absent Redis is supported — but without these the client uses
    # the OS default and retries, and one menu request that touches the cache
    # eight times took 8.15 seconds to return the same answer it would have
    # returned instantly. Redis is either alongside the app or milliseconds
    # away; anything slower is already a failure, so waiting longer only makes
    # the request slower before it misses anyway.
    redis_socket_connect_timeout_seconds: float = 0.25
    # `redis_socket_timeout_seconds` is a per-COMMAND deadline, not just connect,
    # and 0.5s is tuned for a GET: too short and a read never finishes, but a
    # read that times out just costs one query — the request falls through to
    # the database and answers correctly, if a bit slower. A SCAN/DELETE that
    # times out is not a symmetric failure: `cache_delete_pattern` walks
    # `scan_iter`, one slow round trip against a large keyspace raises
    # `RedisError`, the handler swallows it and returns 0, and the keys already
    # matched are never deleted. Nothing else invalidates them, so a menu or
    # offer edit then serves the stale cached copy for the full
    # `redis_cache_ttl_seconds` (three days) instead of failing loudly or
    # falling through. The invalidation path gets its own, longer budget so a
    # slow round trip fails the read timeout it would have anyway rather than
    # abandoning a delete already in progress.
    redis_socket_timeout_seconds: float = 0.5
    redis_delete_socket_timeout_seconds: float = 3.0
    redis_cache_ttl_seconds: int = 259200
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    generated_combo_min_order_count: int = 3
    generated_combo_min_unique_users: int = 1
    generated_combo_min_visible_unique_users: int = 3
    generated_combo_max_size: int = 3
    generated_combo_lookback_days: int = 90
    generated_combo_expiry_days: int = 90
    generated_combo_draft_expiry_days: int = 30
    generated_combo_discount_rate: float = 0.07
    generated_combo_counted_statuses: str = "DELIVERED"
    generated_combo_counted_payment_statuses: str = "PAID,COD"
    new_item_window_days: int = 14
    bestseller_window_days: int = 30
    bestseller_min_valid_orders: int = 25
    bestseller_top_item_count: int = 0
    bestseller_cache_ttl_seconds: int = 21600
    bestseller_counted_statuses: str = "ACCEPTED,PREPARING,OUT_FOR_DELIVERY,DELIVERED"
    personalized_offer_inactivity_days: int = 14
    personalized_offer_cooldown_hours: int = 48
    personalized_offer_cache_ttl_seconds: int = 3600
    personalized_offer_max_cards: int = 4
    enable_ai_offer_generation: bool = False
    enable_ai_recommendation_reranking: bool = False
    # Drops a "dish name" the menu does not recognise — "today", "special",
    # "trending", "delivery" — instead of searching for it and then reporting
    # that it is not on the menu. OFF while the log is read: a threshold that is
    # slightly wrong refuses real orders, which is worse than the bug it fixes.
    # See docs/superpowers/specs/2026-09-14-dish-name-guardrail-design.md
    enable_dish_name_guardrail: bool = False
    ai_offer_cron_enabled: bool = False
    ai_offer_batch_size: int = 50
    ai_offer_user_limit: int = 0
    ai_max_flat_discount: Decimal = Decimal("100.00")
    ai_max_percentage_discount: Decimal = Decimal("30.00")
    ai_min_order_threshold: Decimal = Decimal("99.00")
    ai_offer_validity_days: int = 7
    ai_offer_cron_hour: int = 17
    ai_offer_cron_minute: int = 0
    ollama_offer_timeout_seconds: float = 30.0
    qwen_offer_model_name: str = "qwen3:8b"
    ai_recommendation_candidate_limit: int = 50
    ai_recommendation_final_limit: int = 20
    ai_recommendation_min_candidate_count: int = 10
    ai_recommendation_retry_cooldown_minutes: int = 15
    ai_recommendation_max_same_restaurant: int = 3
    ai_recommendation_max_same_cuisine: int = 4
    ai_recommendation_max_same_category: int = 4

    # AI Restaurant Manager metrics/diagnostics layer.
    #
    # Revenue diagnostics deliberately exclude CANCELLED and PAYMENT_PENDING
    # orders: an abandoned card checkout is not revenue, and counting it makes a
    # period comparison read as growth that never reached the kitchen. This is a
    # known divergence from `get_reports_snapshot`, which counts every status.
    insights_counted_order_statuses: str = "ACCEPTED,PREPARING,OUT_FOR_DELIVERY,DELIVERED"
    insights_cache_ttl_seconds: int = 900
    # Windows end today, so nearly every snapshot covers a day still in
    # progress and keeps moving as orders arrive. Short enough that a new order
    # appears promptly, long enough that a page reload is free.
    insights_partial_day_cache_ttl_seconds: int = 120
    insights_default_window_days: int = 7
    insights_max_window_days: int = 180
    # Below these volumes a period comparison is noise, so the layer reports
    # `insufficient_data` instead of a percentage a small restaurant would act on.
    insights_min_orders_for_delta: int = 10
    insights_min_orders_for_contribution: int = 3
    insights_min_daily_orders_for_anomaly: int = 3
    insights_anomaly_baseline_days: int = 28
    insights_anomaly_min_baseline_days: int = 14
    insights_anomaly_z_threshold: float = 3.0
    insights_top_contributor_limit: int = 8

    # --- WhatsApp concierge -------------------------------------------------
    #
    # The same assistant as the web concierge, reached over WhatsApp. Nothing
    # here is a second brain: the webhook hands the message to the same
    # `handle_chat_message` the web app calls.
    #
    # Off by default like every other channel-level feature, so a deployment
    # without credentials answers nobody rather than half-answering.
    whatsapp_enabled: bool = False

    # The ONE number this bot may answer on, as Meta's numeric id (not the
    # dialling number). Every inbound event names the number it arrived at, and
    # anything that is not this id is dropped without a reply.
    #
    # This matters more than it looks: a WhatsApp number can be shared with
    # another integration, and Meta delivers each message to whoever is
    # subscribed. Two systems answering one message means the customer gets two
    # replies. Empty means "answer nothing", which is the safe way to be
    # misconfigured.
    whatsapp_phone_number_id: str = ""

    # Meta Cloud API credentials. The app secret signs every webhook delivery;
    # the access token is what we send replies with.
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""
    # Chosen by us and echoed back during Meta's one-time subscription check.
    whatsapp_verify_token: str = ""
    whatsapp_api_base_url: str = "https://graph.facebook.com/v21.0"

    # Which restaurant this number speaks for. Set it and the assistant answers
    # from that menu only, the same way a single-restaurant app client does;
    # leave it empty and it behaves like the marketplace app, across all of
    # them.
    whatsapp_restaurant_id: str = ""
    # Which branch a WhatsApp order is placed against. A chat thread has
    # no branch picker, and an order cannot be placed without one — unset
    # means the assistant answers about the menu but cannot take an order,
    # which is better than guessing a branch on somebody's behalf.
    whatsapp_restaurant_location_id: str = ""

    # Who may be answered, as a comma-separated list of sender numbers in the
    # form WhatsApp uses (country code, digits only, no +).
    #
    # Empty means everyone, which is what a real deployment wants. It is not
    # what TESTING wants on a number that belongs to a live business: with the
    # webhook pointed here, that business's customers reach this bot, and they
    # got restaurant recommendations from a tailor's number before this
    # existed. Set it to your own number and everyone else is dropped in
    # silence - no reply is the right answer to someone we should not be
    # talking to at all.
    whatsapp_allowed_senders: str = ""

    # Meta retries a delivery it thinks failed, and a retry must not produce a
    # second reply. Seen message ids are remembered for this long.
    whatsapp_seen_message_ttl_seconds: int = 3600

    # WhatsApp rejects a body over 4096 characters outright, so a long answer is
    # trimmed rather than lost.
    whatsapp_max_body_chars: int = 4000

    # AI Restaurant Manager insight generation and narration.
    #
    # Both flags default off. With narration disabled the feature still works
    # end to end on deterministic templates, which is also the fallback whenever
    # the model is slow, unreachable, or returns numbers it was not given.
    enable_ai_manager_insights: bool = False
    enable_ai_manager_narration: bool = False
    ai_manager_cron_enabled: bool = False
    ai_manager_cron_hour: int = 4
    ai_manager_cron_minute: int = 30
    # Nightly runs are sequential against a CPU-only Ollama host, so a cap keeps
    # one slow night from overrunning into service hours.
    ai_manager_max_restaurants_per_run: int = 100
    ai_manager_narration_timeout_seconds: float = 45.0
    ai_manager_narration_model: str = "qwen3:8b"
    ai_manager_narration_max_tokens: int = 220
    # Rounding tolerance when checking that every number the model wrote came
    # from the fact pack.
    ai_manager_number_tolerance: float = 0.05
    # Above this, a percentage change says more about how quiet the earlier
    # period was than about the business: a week with one order followed by a
    # normal week reads as "up 2859.6%". The money is quoted instead. One
    # threshold for every surface — briefing headline, KPI tiles and chat — so
    # they cannot disagree about the same figure.
    insights_misleading_percent_change: float = 300.0

    # Insight rule thresholds. A movement must clear both the percentage and the
    # absolute floor, so a swing on a tiny base does not become a headline.
    insight_revenue_change_percent: float = 8.0
    insight_revenue_change_minimum: float = 1000.0
    insight_item_contribution_percent: float = 25.0
    insight_category_contribution_percent: float = 25.0
    insight_location_contribution_percent: float = 20.0
    insight_daypart_contribution_percent: float = 25.0
    insight_weekday_contribution_percent: float = 30.0
    insight_cohort_change_percent: float = 15.0
    insight_aov_change_percent: float = 10.0
    insight_cancellation_rate_percent: float = 8.0
    insight_cancellation_minimum_orders: int = 3
    # Severity is capped by the money involved, not only by the share of the
    # change. A finding can be 90% of a movement and still be trivial if the
    # movement itself was small, and calling that HIGH trains an owner to
    # ignore the feed.
    insight_severity_medium_floor: Decimal = Decimal("2000.00")
    insight_severity_high_floor: Decimal = Decimal("5000.00")
    # ...and the same floors expressed as a share of the restaurant's own
    # revenue for the period, because an absolute floor alone means a small
    # restaurant can never produce anything above LOW. Whichever floor is lower
    # applies, so a big restaurant still needs real money to reach HIGH while a
    # $1,300 movement on a $2,700 period is correctly loud.
    # How many bundle suggestions one run may propose. Five near-identical
    # "Bundle X + Y" rows crowded out the findings that actually explained the
    # period; the top pairings by real basket evidence are the useful ones.
    insights_max_combo_proposals: int = 2
    insight_severity_medium_revenue_share: float = 0.10
    insight_severity_high_revenue_share: float = 0.25
    # A category insight is suppressed when a single item explains this much of
    # it, because the two are then the same finding told twice.
    insight_duplicate_share_threshold: float = 0.9
    # Windows tried in order when the default is too sparse to say anything.
    # Widening the window is allowed; lowering the materiality gates is not.
    # Widened to 90. A restaurant taking a handful of orders a week never
    # cleared the volume threshold inside 30 days, so the nightly run skipped it
    # every night and it looked to its owner like the feature was broken. The
    # ladder now reaches a window such a restaurant can actually fill.
    insights_adaptive_window_days: str = "7,30,90"
    insight_max_per_briefing: int = 8
    # How long the same finding stays suppressed after it was last raised, so a
    # continuing slump does not regenerate an identical card every night.
    insight_dedupe_cooldown_hours: int = 72

    # AI Restaurant Manager recommendations and actions.
    #
    # A proposal can spend real money once approved, so generation is flagged
    # off by default and nothing ever executes without an explicit approval
    # call. The discount ceilings are the same ones the AI offer generator uses.
    enable_ai_manager_actions: bool = False

    # --- Marketing Hub dispatch ---------------------------------------------
    #
    # A campaign send is the one thing in this product that reaches a customer's
    # lock screen unprompted, and it cannot be recalled. So the switch that
    # makes it real is separate from the feature: the Hub builds, schedules and
    # reports whether or not this is on, and only this decides whether Firebase
    # is actually called.
    #
    # Off by default for the same reason every AI flag is — a deployment that
    # has not deliberately turned sending on must not discover it by pressing a
    # button. With it off, dispatch runs end to end against the real audience
    # and records exactly what it would have delivered (`sent_count` and the
    # recipient rows are real), marks the campaign SENT, and calls no external
    # service. That is a dry run an owner can inspect, not a silent no-op.
    enable_marketing_dispatch: bool = False

    # How many device tokens go to Firebase in one multicast. 500 is the API's
    # own per-message ceiling; it is named here because the dispatcher reports
    # progress per batch and the batch size is therefore the granularity the
    # owner sees a SENDING campaign move in.
    marketing_dispatch_batch_size: int = 500

    # How long any one call to a channel provider may take. Deliberately short.
    # A dispatch holds a Celery worker for the length of the send, and a
    # gateway that has stopped answering must fail that recipient and let the
    # other nine hundred through rather than stalling the whole campaign
    # behind one socket. Measured against Meta's Graph API, which answers a
    # template send in well under a second when it is healthy at all.
    marketing_provider_timeout_seconds: float = 15.0

    # What one message costs on the channels that charge by the message, in
    # the restaurant's own currency. Named here rather than read from the
    # gateway because no gateway exposes a price list, and an owner deciding
    # whether to send 4,000 texts needs the number before the send, not on
    # the invoice after it. The reach estimate multiplies these by the
    # recipients *and by the parts*, so a long text is costed as the two
    # messages the operator will actually bill.
    # The shared secret an SMS gateway presents when it posts an inbound
    # message back to us. There is no signature standard across Indian
    # aggregators the way Meta and Stripe have one, so this is a token the
    # operator is configured with and sends as `X-Marketing-Token` or `?token=`.
    # Empty means the endpoint refuses everything, which is the right default:
    # an unauthenticated inbound route could opt any customer out by guessing
    # their phone number.
    marketing_sms_inbound_secret: str = ""

    marketing_sms_cost_per_message: float = 0.85
    marketing_whatsapp_cost_per_message: float = 0.85

    # Hard ceilings on what one campaign, and one restaurant in one calendar
    # month, may spend on messages the platform bills through. Enforced, not
    # advisory: the reach estimate raises a blocking notice and the dispatcher
    # re-checks the same notice at send time, so a draft that was under the
    # cap on Tuesday and over it by Friday is refused on Friday.
    #
    # They exist because the failure is silent and expensive. An owner widens
    # a segment from "lapsed regulars" to "everyone", the recipient count goes
    # from 400 to 9,000, and the only thing that changed on screen is a
    # number they were not looking at. Push and the social channels cost
    # nothing and are unaffected by either cap.
    #
    # Zero disables a cap. Left non-zero by default on purpose: a deployment
    # that has not thought about this should be protected, not exposed.
    # Marketing messages one customer may receive in a rolling week, across
    # every campaign from one restaurant and across every channel — three
    # pushes and three texts is six messages to the person receiving them.
    # A setting rather than a constant because the right number is a
    # judgement about a market and a menu, not about this codebase: a daily
    # lunch deal and a monthly newsletter are both legitimate and want very
    # different answers.
    marketing_frequency_cap_per_week: int = 2

    marketing_campaign_spend_cap: float = 5000.0
    marketing_monthly_spend_cap: float = 25000.0

    # How long after a social post goes up its numbers keep being refreshed.
    # Meta's insights lag publication by minutes and keep moving for days;
    # past this the post is no longer news and the polling is pure cost.
    marketing_social_insight_days: int = 7

    # How often beat looks for scheduled campaigns that have come due. A
    # campaign scheduled for 09:00 goes out within this window of it, which is
    # why quiet hours are re-checked at fire time rather than trusted from when
    # the owner scheduled it.
    marketing_scheduler_interval_minutes: int = 5

    # --- Phase 8B: the AI analyst -------------------------------------------
    #
    # Three separate switches on purpose. Running the analyst, writing what it
    # produced, and showing it to an owner are different decisions with
    # different risks, and collapsing them into one flag is how shadow output
    # reaches a user by accident.
    enable_ai_manager_analyst: bool = False
    ai_manager_analyst_shadow_mode: bool = True
    enable_ai_manager_ai_findings: bool = False
    # A window with fewer trading days than this supports no conclusion,
    # however many orders those days happen to contain.
    analyst_min_trading_days: int = 3
    # Two of these are seeded deterministically, so the model still chooses
    # the interesting half. Twelve was never reached before a budget was.
    analyst_max_tool_calls: int = 6
    analyst_prompt_version: str = "8e"
    # Additive mode: one short generation replaces the explore/conclude pair.
    analyst_commentary_timeout_seconds: float = 240.0
    analyst_commentary_max_tokens: int = 400
    # Budgets. On a CPU-only Ollama host each generation is tens of seconds, so
    # the loop is bounded three ways: how many questions it may ask, how long
    # the whole run may take, and how much of any one result it may read.
    analyst_model: str = "qwen3:8b"
    # Measured on this CPU host: explore ~40s, conclude ~314s at 796 output
    # tokens (~2.5 tok/s). Budgets set from those numbers, with headroom,
    # rather than from an estimate.
    analyst_time_budget_seconds: float = 900.0
    analyst_explore_timeout_seconds: float = 90.0
    analyst_conclude_timeout_seconds: float = 480.0
    analyst_max_result_chars: int = 2200
    analyst_conclude_result_chars: int = 1100
    analyst_max_repeated_calls: int = 2
    analyst_explore_max_tokens: int = 160
    # Sized against the conclude schema: the first live run truncated mid-JSON
    # at 900, which reads as malformed output rather than as a budget.
    # Generation is serial and token-bound, so output length is the single
    # biggest lever on run time. Two findings is enough to be useful.
    analyst_conclude_max_tokens: int = 1200
    analyst_temperature: float = 0.2
    action_max_open_proposals: int = 6
    action_proposal_expiry_days: int = 14
    # A recovery assumption, not a forecast: a promotion is credited with
    # winning back this share of what was lost. Every impact figure derived from
    # it is labelled an estimate.
    action_recovery_rate: float = 0.5
    action_default_discount_percent: Decimal = Decimal("10.00")
    action_winback_discount_percent: Decimal = Decimal("15.00")
    action_welcome_discount_percent: Decimal = Decimal("20.00")
    action_default_valid_for_days: int = 7
    action_default_minimum_order: Decimal = Decimal("199.00")
    action_combo_min_confidence: Decimal = Decimal("5.00")

    # Action outcome measurement.
    #
    # An offer needs time to be seen and used, so an outcome is only measured
    # once it has run for this long. Measuring sooner would report "no uptake"
    # for offers that simply had not been shown yet.
    action_outcome_maturity_days: int = 7
    action_outcome_max_window_days: int = 30
    action_outcome_batch_limit: int = 100
    # How close to the estimate counts as having met it, either way.
    action_outcome_met_tolerance: float = 0.2

    # AI Restaurant Manager owner chat.
    #
    # Answers are assembled from the same deterministic skills the rest of the
    # manager uses; the model only supplies wording, and only when narration is
    # enabled. With it off, chat still answers from templates.
    enable_ai_manager_chat: bool = False
    # The router tries rules first and only calls the model when they miss. On a
    # CPU-only host a routing call plus a wording call is the difference between
    # a 20-second and a 60-second answer, so the routing call is kept tiny.
    enable_ai_manager_chat_llm_router: bool = True

    # --- Tier 2: tool-backed chat -------------------------------------------
    #
    # One extraction call that may pick a read-only data tool instead of a
    # skill. Off by default: it is the first path that lets a model decide which
    # of the owner's data is read, and that deserves an explicit switch.
    enable_ai_manager_chat_tools: bool = True
    chat_tool_planner_model: str = "qwen3:8b"
    chat_tool_planner_timeout_seconds: float = 45.0
    chat_tool_planner_max_tokens: int = 90
    # How long a question-to-tool mapping is reused. Long, because the mapping
    # is a property of the wording rather than of the data: what "was anything
    # out of stock" means does not change when an order arrives.
    chat_tool_plan_cache_ttl_seconds: int = 86400

    # --- Customer-facing ordering agent's planner (Task 4) ------------------
    #
    # A sibling of the chat_tool_planner_* block above, not a reuse of it: this
    # one is multi-round (the loop feeds each tool's result back and calls the
    # planner again until it answers), so a plan here depends on the cart and
    # on what already happened this turn, never on the question's wording
    # alone — there is deliberately no cache_ttl setting to go with it, unlike
    # chat_tool_plan_cache_ttl_seconds above, because caching by wording would
    # serve one customer's half-built cart to a different customer who typed
    # the same sentence.
    ordering_agent_model: str = "qwen3:8b"
    ordering_agent_planner_timeout_seconds: float = 45.0
    # 400, not chat_tool_planner_max_tokens' 90: that budget only ever writes
    # a tool name and a few arguments. This planner's other shape is the
    # customer-facing reply itself (`{"answer": "..."}`), and a sentence or
    # two of real prose needs more room than an owner-side tool pick ever did.
    ordering_agent_planner_max_tokens: int = 400

    # --- Customer-facing ordering agent's loop (Task 5) ----------------------
    #
    # Off by default per the house rule every AI flag here follows: with this
    # false, `loop.run_turn` never calls the planner, never runs a tool, and
    # returns `fallback_reason="flag_off"` immediately, so Task 6's chat turn
    # can wire this in ahead of anyone actually turning it on.
    enable_ordering_agent: bool = False
    # A customer's turn is at most this many plan-then-tool rounds before the
    # loop gives up and falls back — not measured yet, since nothing has run
    # against a real model or a real cart: a placeholder chosen to be "enough
    # rounds for get_dish -> add_to_cart or view_cart -> price_quote, plus one
    # spare for a self-correction," never exercised end to end. Task 8
    # measures a real turn's round count and may move this.
    ordering_agent_max_tool_rounds: int = 6
    # Wall-clock ceiling for a whole turn (every plan_step call plus every
    # tool call), independent of `ordering_agent_planner_timeout_seconds`
    # (which bounds one model call, not the turn). Also not measured yet —
    # picked as "a customer will wait this long for a chat reply before it
    # reads as broken," not from timing data. Task 8 measures and may move
    # this alongside the round cap above.
    ordering_agent_budget_seconds: float = 30.0

    ai_manager_router_timeout_seconds: float = 20.0
    ai_manager_router_max_tokens: int = 80
    # The window a chat question covers when the owner names no period at all.
    # Deliberately NOT `insights_default_window_days`: that one paces the
    # nightly analysis, where a week is the right cadence for spotting a change.
    # An owner asking "which dish sells best?" means their menu in general, and
    # answering from seven days of trade judged a menu on a handful of orders.
    ai_manager_chat_default_window_days: int = 90
    ai_manager_chat_history_messages: int = 20
    ai_manager_chat_max_question_chars: int = 500

    # --- Final answer generation --------------------------------------------
    #
    # Qwen writes the reply an owner reads, from validated facts it is handed.
    # Deliberately NOT `enable_ai_manager_narration`: that flag also governs the
    # briefing, and reusing it would silently turn on owner-facing briefing
    # narration as a side effect of enabling chat answers. Two audiences, two
    # switches.
    #
    # With this off, chat still answers end to end from the deterministic
    # formatters — which remain the fallback whenever the model is slow,
    # unreachable, or writes a figure it was not given.
    enable_ai_manager_chat_answers: bool = True
    ai_manager_chat_answer_model: str = "qwen3:8b"
    # Sized to the host, which generates about 3 tokens a second on CPU. A
    # 700-token budget could not physically finish inside a minute, so every
    # long answer timed out and fell back after making the owner wait for it.
    # Measured throughput moves between roughly 1.4 and 3 tokens a second
    # depending on what else the host is doing, so the budget is sized for the
    # slow end: 120 tokens still lands inside the timeout at 1.4/s, where 150
    # did not and every answer fell back after making the owner wait for it.
    ai_manager_chat_answer_timeout_seconds: float = 110.0
    # Sized to what an answer actually needs rather than to the worst case. On a
    # host generating ~3 tokens a second every unnecessary token is a third of a
    # second the owner waits, and the old 280 let simple questions ramble into
    # 40-second answers. Multi-part questions get more, in proportion to how
    # many parts they have to cover.
    ai_manager_chat_answer_max_tokens: int = 120
    ai_manager_chat_answer_tokens_per_part: int = 45
    ai_manager_chat_answer_max_chars: int = 900
    # A generated answer is reused only while BOTH the question and the facts
    # behind it are unchanged, so it can never outlive the data it describes.
    ai_manager_chat_answer_cache_ttl_seconds: int = 900

    # Stripe is the only live payment provider. Secrets come from the
    # environment; the mock defaults keep local boot working but are treated as
    # "card unavailable" by `stripe_is_configured`.
    stripe_secret_key: str = "sk_test_mock"
    stripe_publishable_key: str = "pk_test_mock"
    stripe_webhook_secret: str = ""
    stripe_api_version: str = "2024-11-20.acacia"
    # Every customer-facing price is rendered in CAD, so the charge currency
    # has to agree — a Stripe intent in another currency would show the
    # customer one number on the checkout screen and bill them a different one.
    # USD since 8f4d050 switched every customer- and owner-facing price to it.
    # This setting is NOT cosmetic: orders stamp `orders.currency` from it at
    # creation and the Stripe intent is built from that, so a value the screen
    # does not show charges the customer in a currency nobody quoted. It was
    # "cad" here while .env said "inr" and the apps rendered USD — three
    # currencies for one number.
    # Where Stripe sends the customer back after a hosted checkout. The card
    # sheet never needed this because it never left the page; a payment link
    # does. Overridden per deployment — the default is this machine's dev
    # server, which is where it is used today.
    frontend_base_url: str = "http://localhost:5173"
    # Where THIS API is reachable from a customer's phone — the tunnel while
    # developing, the Render URL in production. An order placed in a chat is
    # paid on a phone, and Stripe then sends the phone to `frontend_base_url`,
    # which on the phone is the phone: the payment landed and the last thing
    # the customer saw was a browser error. Empty means chat orders fall back
    # to the frontend URLs, exactly as web orders always do.
    public_base_url: str = ""
    # The WhatsApp number customers message, digits only, for the "back to
    # the chat" link on that page. Not derivable from the phone-number id
    # Meta gives the API, which is an id and not the number.
    whatsapp_business_number: str = ""
    # Whether a restaurant must hold its own gateway account to take card.
    #
    # Off during the transition, and that is the honest default: every
    # restaurant onboarded before gateway accounts existed is still settled
    # through this deployment's own Stripe keys, and flipping this without
    # warning would stop their checkout. The admin screen says which account
    # is settling a restaurant, so the fallback is visible rather than
    # assumed.
    #
    # On is the correct end state: a restaurant with no account of its own
    # cannot take card, because the alternative is its customers' money
    # landing in the platform's account.
    payments_require_restaurant_account: bool = False
    payment_currency: str = "usd"
    # The key that protects credentials this platform holds on behalf of a
    # tenant — a restaurant's WhatsApp access token, its webhook verify token.
    # Kept out of the database on purpose, so a dump of the channels table is
    # useless on its own. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Unset means this deployment refuses to store somebody else's secret,
    # which is the honest failure — see `services/secrets.py`.
    secrets_encryption_key: str = ""
    # The domain tenant storefronts hang off: a restaurant onboarded with the
    # app key "bangkokbowl" is served at bangkokbowl.<this>. One deployment,
    # one wildcard certificate, and onboarding a restaurant is a row rather
    # than a release. A tenant's own domain is a second row on the same client.
    platform_domain: str = "localhost"
    # Whether this deployment takes cash on delivery at all. Off: this product
    # is card-only, and an always-available COD meant "Place order" completed
    # without any payment step, which read as the payment being skipped.
    # Turning it on is a business decision, not a fallback for missing keys —
    # if Stripe is unconfigured the honest outcome is "card unavailable", not a
    # silent switch to taking cash.
    enable_cash_on_delivery: bool = False
    # How long an unpaid card order survives before the reaper cancels it.
    payment_intent_ttl_minutes: int = 30
    razorpay_key_id: str = "rzp_test_mock"
    razorpay_key_secret: str = "razorpay_mock_secret"

    fcm_project_id: str = "quickbite-7833a"
    fcm_credentials_path: str = "firebase-service-account.json"

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_flag(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "development"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "production"}:
                return False
        return value

    @property
    def backend_cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def cors_origin_regex(self) -> str:
        """The origin pattern, including every tenant's own storefront.

        Naming origins exactly stops being possible the moment onboarding a
        restaurant issues it a subdomain: the list would need a new entry, and
        a redeploy, per restaurant — which is the release-per-tenant this whole
        design exists to avoid. So the pattern is derived from
        `platform_domain`, the same setting that generates those subdomains.
        One source of truth: an address this platform issues is an address this
        platform accepts.

        It admits one label of subdomain, not `.*`, so it matches what
        `platform_host_for` actually produces and nothing deeper.

        `backend_cors_origin_regex` still wins when set, because it exists for
        the case this cannot know about — a LAN address during device testing,
        or a tenant's own domain.
        """

        configured = (self.backend_cors_origin_regex or "").strip()
        domain = (self.platform_domain or "").strip().lstrip(".")
        if not domain:
            return configured

        # A port is optional and only ever appears in development; production
        # storefronts answer on 80 and 443, which browsers omit.
        tenants = rf"https?://[a-z0-9-]+\.{re.escape(domain)}(:\d+)?"
        if not configured:
            return tenants
        return f"({configured})|({tenants})"

    @property
    def stripe_is_configured(self) -> bool:
        """True when real Stripe credentials are present.

        The mock placeholders ship as defaults so the app boots without Stripe;
        card payments stay unavailable until real keys are supplied.
        """

        return (
            bool(self.stripe_secret_key)
            and not self.stripe_secret_key.endswith("_mock")
            and bool(self.stripe_publishable_key)
            and not self.stripe_publishable_key.endswith("_mock")
        )

    @property
    def ollama_embedding_url(self) -> str:
        """The host embeddings go to. Falls back to the generation host.

        Keeping the fallback means an all-local deployment sets nothing new: both
        resolve to the same Ollama. Only a split deployment — cloud generation,
        local embeddings — has to name the second host.
        """

        return self.ollama_embedding_base_url or self.ollama_base_url

    @property
    def ollama_is_cloud(self) -> bool:
        """Whether generation targets a remote Ollama rather than a local one.

        Judged from the HOST, not from whether an API key happens to be set. The
        two are not the same question, and conflating them regresses local
        development: a key left in `.env` while `OLLAMA_BASE_URL` still points at
        localhost would strip `keep_alive` from a local server, costing a model
        reload on every single call.

        Only affects which request options are sent. Authentication is decided
        separately, by whether a key exists, so a self-hosted Ollama behind an
        authenticating proxy still receives its token.
        """

        from urllib.parse import urlparse

        host = (urlparse(self.ollama_base_url).hostname or "").lower()
        return host not in _LOCAL_OLLAMA_HOSTS and not host.endswith(".local")

    @staticmethod
    def normalize_database_url(url: str) -> str:
        """Name the psycopg (v3) driver explicitly in a provider-supplied URL.

        Render's `DATABASE_URL` is `postgresql://...`, and several providers
        still emit the legacy `postgres://` form. SQLAlchemy maps BOTH to
        psycopg2, which this image does not ship — requirements.txt pins
        `psycopg[binary]` v3 — so either form would fail at import with
        `ModuleNotFoundError: No module named 'psycopg2'`, before a single
        request or migration ran. Rewriting only the scheme leaves credentials,
        host, port, database and any query string (`?sslmode=require`) exactly
        as the provider issued them.
        """

        scheme, separator, rest = url.partition("://")
        if not separator or scheme.startswith("postgresql+"):
            return url
        if scheme in {"postgres", "postgresql"}:
            return f"postgresql+psycopg://{rest}"
        return url

    @property
    def sqlalchemy_database_uri(self) -> str:
        if self.database_url:
            return self.normalize_database_url(self.database_url)
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_server}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def generated_combo_counted_statuses_list(self) -> list[str]:
        return [
            status.strip().upper()
            for status in self.generated_combo_counted_statuses.split(",")
            if status.strip()
        ]

    @property
    def bestseller_counted_statuses_list(self) -> list[str]:
        return [
            status.strip().upper()
            for status in self.bestseller_counted_statuses.split(",")
            if status.strip()
        ]

    @property
    def generated_combo_counted_payment_statuses_list(self) -> list[str]:
        return [
            status.strip().upper()
            for status in self.generated_combo_counted_payment_statuses.split(",")
            if status.strip()
        ]

    @property
    def insights_adaptive_window_days_list(self) -> list[int]:
        windows: list[int] = []
        for raw_value in self.insights_adaptive_window_days.split(","):
            value = raw_value.strip()
            if not value:
                continue
            try:
                parsed = int(value)
            except ValueError:
                continue
            if 0 < parsed <= self.insights_max_window_days:
                windows.append(parsed)
        return sorted(dict.fromkeys(windows)) or [self.insights_default_window_days]



    @property
    def insights_counted_order_statuses_list(self) -> list[str]:
        return [
            status.strip().upper()
            for status in self.insights_counted_order_statuses.split(",")
            if status.strip()
        ]

    @property
    def business_timezone_info(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.business_timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")


@lru_cache
def get_settings() -> Settings:
    return Settings()
