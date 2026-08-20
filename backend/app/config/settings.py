from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    # App client that owns customers who arrive without a bundle id
    # (the customer web app), and the fallback identity scope.
    default_app_client_key: str = "marketplace"

    backend_cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173,http://localhost:5174,http://localhost:8081"
    )

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
    ollama_embedding_timeout_seconds: float = 20.0
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
    # ₹1,300 movement on a ₹2,700 period is correctly loud.
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
    payment_currency: str = "inr"
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

    @property
    def sqlalchemy_database_uri(self) -> str:
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
