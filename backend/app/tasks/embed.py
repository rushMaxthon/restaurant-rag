from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.models.menu_embedding import MenuEmbedding
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant

from app.services.embeddings import EmbeddingError, embedding_signature, get_embedding

settings = get_settings()
logger = logging.getLogger(__name__)


def _format_embedding_text(menu_item: MenuItem, restaurant: Restaurant) -> str:
    cuisine = menu_item.cuisine_type or restaurant.cuisine_type
    description = menu_item.description or "No description"
    veg_label = "Veg" if menu_item.is_veg else "Non-Veg"
    price = f"{Decimal(menu_item.price):.2f}"
    return f"{menu_item.name} | {cuisine} | {menu_item.category} | {description} | {price} | {veg_label}"


def _fetch_embedding(source_text: str) -> list[float]:
    """A menu item's vector, from whichever provider is configured.

    Menu text is the DOCUMENT side of the retrieval pair; the customer's message
    is the query side. Gemini embeds the two differently and retrieval is better
    for it, so the distinction is passed through rather than defaulted.

    `EmbeddingError` is re-raised as `RuntimeError` because that is what this
    task's `autoretry_for` is configured to retry — a transient rate limit or a
    dropped connection should come back, not silently leave an item unsearchable.
    """

    try:
        return get_embedding(source_text, task="document")
    except EmbeddingError as error:
        logger.warning("Menu embedding failed: %s", error)
        raise RuntimeError(str(error)) from error


@celery_app.task(
    name="app.tasks.embed.embed_menu_item",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def embed_menu_item(self: Any, menu_item_id: str) -> dict[str, str]:
    menu_item_uuid = uuid.UUID(menu_item_id)

    with SessionLocal() as db:
        row = db.execute(
            select(MenuItem, Restaurant)
            .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
            .where(MenuItem.id == menu_item_uuid)
        ).first()

        if row is None:
            raise RuntimeError(f"Menu item {menu_item_id} was not found")

        menu_item, restaurant = row
        source_text = _format_embedding_text(menu_item, restaurant)
        vector = _fetch_embedding(source_text)

        upsert_stmt = insert(MenuEmbedding).values(
            menu_item_id=menu_item.id,
            source_text=source_text,
            embedding=vector,
        )
        upsert_stmt = upsert_stmt.on_conflict_do_update(
            index_elements=[MenuEmbedding.menu_item_id],
            set_={
                "source_text": upsert_stmt.excluded.source_text,
                "embedding": upsert_stmt.excluded.embedding,
            },
        )

        db.execute(upsert_stmt)
        db.commit()

    logger.info("Embedded menu item %s successfully", menu_item_id)
    return {"status": "embedded", "menu_item_id": menu_item_id}


# --- bulk backfill ----------------------------------------------------------
#
# Menu items only ever got embedded when someone created or edited one through
# the admin API, so a restaurant that existed before embeddings were switched on
# has none — and its dishes are invisible to vector search forever. This is the
# missing half: embed everything that has no vector, or everything at all after
# a provider change.

SIGNATURE_CACHE_KEY = "embeddings:signature"


def _stored_signature() -> str | None:
    from app.services.cache import cache_get_json

    value = cache_get_json(SIGNATURE_CACHE_KEY)
    return value if isinstance(value, str) else None


def _remember_signature(signature: str) -> None:
    from app.services.cache import cache_set_json

    # No TTL semantics wanted here, so it is written with a long one: this is a
    # marker of which vector space the stored rows belong to, not a cache entry.
    cache_set_json(SIGNATURE_CACHE_KEY, signature, ttl_seconds=60 * 60 * 24 * 365)


@celery_app.task(
    name="app.tasks.embed.backfill_menu_embeddings",
    bind=True,
)
def backfill_menu_embeddings(
    self: Any,
    *,
    restaurant_id: str | None = None,
    only_missing: bool = True,
    force: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """Embed menu items in bulk with the currently configured provider.

    `only_missing=True` (the default) embeds items that have no vector yet, which
    is the safe everyday case. `only_missing=False` re-embeds everything, which
    is what a provider change requires.

    The signature guard is requirement 12 made enforceable. Ollama and Gemini
    vectors are not comparable, so mixing them in one table silently corrupts
    similarity search — cosine distance still returns rows, just meaningless
    ones. If the configured provider differs from the one that produced the
    stored rows, this refuses to run rather than adding to the mess. `force=True`
    proceeds and should be paired with `only_missing=False` so the whole table
    ends up in one vector space.
    """

    signature = embedding_signature()
    previous = _stored_signature()
    mixing = previous is not None and previous != signature

    if mixing and not force:
        logger.error(
            "Refusing to backfill: stored vectors were produced by %s, configured "
            "provider is %s. Vectors from different models are not comparable. "
            "Re-run with force=True and only_missing=False to rebuild the table.",
            previous,
            signature,
        )
        return {
            "status": "refused",
            "reason": "provider_mismatch",
            "stored_signature": previous,
            "configured_signature": signature,
        }

    embedded = failed = skipped = 0
    with SessionLocal() as db:
        query = (
            select(MenuItem, Restaurant)
            .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
            .order_by(MenuItem.created_at)
        )
        if restaurant_id is not None:
            query = query.where(MenuItem.restaurant_id == uuid.UUID(restaurant_id))
        if only_missing and not mixing:
            existing = select(MenuEmbedding.menu_item_id)
            query = query.where(MenuItem.id.not_in(existing))
        if limit is not None:
            query = query.limit(limit)

        rows = db.execute(query).all()
        logger.info(
            "Backfill starting items=%d provider=%s only_missing=%s",
            len(rows),
            signature,
            only_missing,
        )

        for menu_item, restaurant in rows:
            source_text = _format_embedding_text(menu_item, restaurant)
            try:
                vector = get_embedding(source_text, task="document")
            except EmbeddingError as error:
                # One dish failing must not abandon the other 189. A rate limit
                # on a free tier is expected partway through a large run.
                failed += 1
                logger.warning("Backfill skipped %s: %s", menu_item.id, error)
                continue

            upsert_stmt = insert(MenuEmbedding).values(
                menu_item_id=menu_item.id,
                source_text=source_text,
                embedding=vector,
            )
            upsert_stmt = upsert_stmt.on_conflict_do_update(
                index_elements=[MenuEmbedding.menu_item_id],
                set_={
                    "source_text": upsert_stmt.excluded.source_text,
                    "embedding": upsert_stmt.excluded.embedding,
                },
            )
            db.execute(upsert_stmt)
            embedded += 1

        db.commit()

    if embedded:
        _remember_signature(signature)

    summary = {
        "status": "completed",
        "provider": signature,
        "embedded": embedded,
        "failed": failed,
        "skipped": skipped,
    }
    logger.info("Backfill finished %s", summary)
    return summary
