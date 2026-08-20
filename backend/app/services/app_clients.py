from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.app_client import (
    BRANDING_PRIMARY_COLOR_KEY,
    CONFIG_MINIMUM_SUPPORTED_VERSION_KEY,
    AppClient,
    AppClientIdentifier,
    AppClientOrderSequence,
)
from app.models.enums import AppClientEnvironment, AppClientPlatform, AppClientStatus, AppMode
from app.models.restaurant import Restaurant
from app.schemas.app_config import AppConfigResponse
from app.schemas.restaurant import (
    APP_KEY_MAX_LENGTH,
    ORDER_NUMBER_PREFIX_MAX_LENGTH,
    AdminRestaurantCreate,
    AppClientUpsertRequest,
)

logger = logging.getLogger(__name__)

DEFAULT_APP_CLIENT_DISPLAY_NAME = "QuickBite"
BUNDLE_ID_NAMESPACE = "com.quickbite"
DEFAULT_BRAND_PRIMARY_COLOR = "#E23744"
DEFAULT_MINIMUM_SUPPORTED_VERSION = "1.0.0"
DEFAULT_ORDER_NUMBER_PREFIX = "ORD"


def _to_app_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"app_{normalized}" if normalized else "app"
    return normalized[:APP_KEY_MAX_LENGTH]


def _to_bundle_segment(app_key: str) -> str:
    """Bundle id segments cannot start with a digit or contain underscores."""

    segment = app_key.replace("_", "")
    if not segment or not segment[0].isalpha():
        segment = f"app{segment}"
    return segment


def _to_order_number_prefix(restaurant_name: str) -> str:
    words = [word for word in re.split(r"[^A-Za-z0-9]+", restaurant_name) if word]
    initials = "".join(word[0] for word in words if word[0].isalpha()).upper()
    if len(initials) >= 2:
        return initials[:ORDER_NUMBER_PREFIX_MAX_LENGTH]

    letters = re.sub(r"[^A-Za-z]", "", restaurant_name).upper()
    if len(letters) >= 2:
        return letters[:4]
    return DEFAULT_ORDER_NUMBER_PREFIX


def _is_app_key_taken(
    db: Session,
    app_key: str,
    *,
    exclude_app_client_id: uuid.UUID | None = None,
) -> bool:
    query = select(AppClient.id).where(AppClient.key == app_key)
    if exclude_app_client_id is not None:
        query = query.where(AppClient.id != exclude_app_client_id)
    return db.scalar(query) is not None


def _is_identifier_taken(
    db: Session,
    *,
    platform: AppClientPlatform,
    identifier: str,
    exclude_app_client_id: uuid.UUID | None = None,
) -> bool:
    """Identifiers are unique per (platform, identifier, environment)."""

    query = select(AppClientIdentifier.id).where(
        AppClientIdentifier.platform == platform,
        AppClientIdentifier.identifier == identifier,
        AppClientIdentifier.environment == AppClientEnvironment.PROD,
    )
    if exclude_app_client_id is not None:
        query = query.where(AppClientIdentifier.app_client_id != exclude_app_client_id)
    return db.scalar(query) is not None


def _generate_unique_app_key(db: Session, restaurant_name: str) -> str:
    base_key = _to_app_key(restaurant_name)
    candidate = base_key
    suffix = 2

    while _is_app_key_taken(db, candidate):
        candidate = f"{base_key}_{suffix}"
        suffix += 1
    return candidate


def _generate_unique_bundle_id(db: Session, app_key: str) -> str:
    base_bundle_id = f"{BUNDLE_ID_NAMESPACE}.{_to_bundle_segment(app_key)}"
    candidate = base_bundle_id
    suffix = 2

    while _is_identifier_taken(
        db, platform=AppClientPlatform.IOS, identifier=candidate
    ) or _is_identifier_taken(db, platform=AppClientPlatform.ANDROID, identifier=candidate):
        candidate = f"{base_bundle_id}{suffix}"
        suffix += 1
    return candidate


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def validate_app_client_identity_is_available(
    db: Session,
    *,
    app_key: str,
    ios_bundle_id: str,
    android_package_name: str,
    exclude_app_client_id: uuid.UUID | None = None,
) -> None:
    """Reject an app identity that collides with a different app client."""

    if _is_app_key_taken(db, app_key, exclude_app_client_id=exclude_app_client_id):
        raise _conflict(f"App key '{app_key}' is already used by another app client")

    if _is_identifier_taken(
        db,
        platform=AppClientPlatform.IOS,
        identifier=ios_bundle_id,
        exclude_app_client_id=exclude_app_client_id,
    ):
        raise _conflict(f"iOS bundle ID '{ios_bundle_id}' is already used by another app client")

    if _is_identifier_taken(
        db,
        platform=AppClientPlatform.ANDROID,
        identifier=android_package_name,
        exclude_app_client_id=exclude_app_client_id,
    ):
        raise _conflict(f"Android package name '{android_package_name}' is already used by another app client")


@dataclass(frozen=True)
class AppClientIdentity:
    app_key: str
    app_mode: AppMode
    ios_bundle_id: str
    android_package_name: str
    order_number_prefix: str
    brand_primary_color: str
    minimum_supported_version: str


def resolve_app_client_identity(
    db: Session,
    *,
    restaurant_name: str,
    app_key: str | None = None,
    app_mode: AppMode | None = None,
    ios_bundle_id: str | None = None,
    android_package_name: str | None = None,
    order_number_prefix: str | None = None,
    brand_primary_color: str | None = None,
    minimum_supported_version: str | None = None,
) -> AppClientIdentity:
    """Fill in any app identity value that was not supplied.

    Supplied values are used as-is; missing ones are derived from the restaurant
    name, with collision suffixing on the generated keys and bundle ids.
    """

    resolved_app_key = app_key or _generate_unique_app_key(db, restaurant_name)
    resolved_ios_bundle_id = ios_bundle_id or _generate_unique_bundle_id(db, resolved_app_key)
    return AppClientIdentity(
        app_key=resolved_app_key,
        app_mode=app_mode or AppMode.SINGLE_RESTAURANT,
        ios_bundle_id=resolved_ios_bundle_id,
        android_package_name=android_package_name or resolved_ios_bundle_id,
        order_number_prefix=order_number_prefix or _to_order_number_prefix(restaurant_name),
        brand_primary_color=brand_primary_color or DEFAULT_BRAND_PRIMARY_COLOR,
        minimum_supported_version=minimum_supported_version or DEFAULT_MINIMUM_SUPPORTED_VERSION,
    )


def _new_prod_identifiers(identity: AppClientIdentity) -> list[AppClientIdentifier]:
    return [
        AppClientIdentifier(
            platform=AppClientPlatform.IOS,
            identifier=identity.ios_bundle_id,
            environment=AppClientEnvironment.PROD,
            is_active=True,
        ),
        AppClientIdentifier(
            platform=AppClientPlatform.ANDROID,
            identifier=identity.android_package_name,
            environment=AppClientEnvironment.PROD,
            is_active=True,
        ),
    ]


def create_app_client(
    *,
    restaurant_id: uuid.UUID,
    display_name: str,
    identity: AppClientIdentity,
) -> AppClient:
    app_client = AppClient(
        key=identity.app_key,
        display_name=display_name,
        app_mode=identity.app_mode,
        restaurant_id=restaurant_id,
        status=AppClientStatus.ACTIVE,
        order_number_prefix=identity.order_number_prefix,
        branding={BRANDING_PRIMARY_COLOR_KEY: identity.brand_primary_color},
        config={CONFIG_MINIMUM_SUPPORTED_VERSION_KEY: identity.minimum_supported_version},
    )
    app_client.identifiers = _new_prod_identifiers(identity)
    app_client.order_sequence = AppClientOrderSequence(last_value=0)
    return app_client


def build_app_client_for_restaurant(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    restaurant_name: str,
    payload: AdminRestaurantCreate,
) -> AppClient:
    """Build the app client created alongside a new restaurant.

    Explicit values from the admin form are validated strictly and never
    auto-corrected. Omitted values are derived from the restaurant name so the
    pre-existing create-restaurant contract keeps working.

    The app client is always linked to the restaurant being created, including
    in `MARKETPLACE` mode; unlinked marketplace clients are managed elsewhere.
    """

    identity = resolve_app_client_identity(
        db,
        restaurant_name=restaurant_name,
        app_key=payload.app_key,
        app_mode=payload.app_mode,
        ios_bundle_id=payload.ios_bundle_id,
        android_package_name=payload.android_package_name,
        order_number_prefix=payload.order_number_prefix,
        brand_primary_color=payload.brand_primary_color,
        minimum_supported_version=payload.minimum_supported_version,
    )

    validate_app_client_identity_is_available(
        db,
        app_key=identity.app_key,
        ios_bundle_id=identity.ios_bundle_id,
        android_package_name=identity.android_package_name,
    )

    return create_app_client(
        restaurant_id=restaurant_id,
        display_name=restaurant_name,
        identity=identity,
    )


def parse_app_client_platform(value: str | None) -> AppClientPlatform | None:
    """Parse a client-supplied platform name, tolerating case and spacing.

    Returns None for anything unrecognised so that a malformed header degrades
    to platform-agnostic matching instead of failing the request.
    """

    if not value:
        return None

    normalized = value.strip().upper()
    try:
        return AppClientPlatform(normalized)
    except ValueError:
        return None


def find_app_client_by_bundle_id(
    db: Session,
    *,
    bundle_id: str,
    platform: AppClientPlatform | None = None,
) -> AppClient | None:
    """Look up the app client owning a bundle ID, or None when unregistered.

    Identifiers are unique per (platform, identifier, environment), so a bundle
    ID can in principle belong to different app clients on iOS and Android.
    When the caller reports its platform the match is exact; without it, any
    platform matches and the oldest identifier wins.
    """

    normalized_bundle_id = bundle_id.strip()
    if not normalized_bundle_id:
        return None

    query = (
        select(AppClient)
        .join(AppClientIdentifier, AppClientIdentifier.app_client_id == AppClient.id)
        .where(
            AppClientIdentifier.identifier == normalized_bundle_id,
            AppClientIdentifier.environment == AppClientEnvironment.PROD,
            AppClientIdentifier.is_active.is_(True),
        )
    )
    if platform is not None:
        query = query.where(AppClientIdentifier.platform == platform)

    return db.scalar(query.order_by(AppClientIdentifier.created_at.asc()).limit(1))


def resolve_app_client_by_bundle_id(
    db: Session,
    *,
    bundle_id: str,
    platform: AppClientPlatform | None = None,
) -> AppClient:
    """Resolve a bundle ID to its app client, raising when it cannot be used.

    Only active PROD identifiers resolve, and only active app clients are
    accepted. Used by `/app-config`, where an unusable app must be told so
    explicitly.
    """

    normalized_bundle_id = bundle_id.strip()
    if not normalized_bundle_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide the app bundle ID via the X-App-Bundle-Id header or the bundle_id query parameter",
        )

    app_client = find_app_client_by_bundle_id(
        db,
        bundle_id=normalized_bundle_id,
        platform=platform,
    )

    if app_client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No app is registered for bundle ID '{normalized_bundle_id}'",
        )

    if app_client.status != AppClientStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This app is {app_client.status.value.lower()} and cannot be used",
        )

    return app_client


@dataclass(frozen=True)
class AppScope:
    """Which restaurants the calling app is allowed to see.

    Resolved once per request from the caller's bundle ID. Clients that send no
    bundle ID (the customer web app, the admin panel, direct API use) resolve to
    the unscoped marketplace scope, so existing behaviour is unchanged.
    """

    mode: AppMode = AppMode.MARKETPLACE
    restaurant_id: uuid.UUID | None = None
    app_client_id: uuid.UUID | None = None
    app_key: str | None = None
    bundle_id: str | None = None
    platform: AppClientPlatform | None = None
    status: AppClientStatus | None = None

    @property
    def is_single_restaurant(self) -> bool:
        return self.mode == AppMode.SINGLE_RESTAURANT and self.restaurant_id is not None

    @property
    def restaurant_filter_id(self) -> uuid.UUID | None:
        """The restaurant every query must be narrowed to, or None if unscoped."""

        return self.restaurant_id if self.is_single_restaurant else None

    def allows_restaurant(self, restaurant_id: uuid.UUID | None) -> bool:
        scoped_restaurant_id = self.restaurant_filter_id
        if scoped_restaurant_id is None:
            return True
        return restaurant_id == scoped_restaurant_id


UNSCOPED_APP_SCOPE = AppScope()


def resolve_app_scope(
    db: Session,
    *,
    bundle_id: str | None,
    platform_value: str | None = None,
) -> AppScope:
    """Resolve the request's app scope. Never raises.

    An unknown bundle ID resolves to the unscoped marketplace scope rather than
    an error, so that data endpoints stay available to every existing client.
    A suspended or offboarded app keeps its restaurant scope instead of being
    widened to the whole marketplace; whether such an app should be blocked
    outright is enforced separately, not here.
    """

    if not bundle_id or not bundle_id.strip():
        return UNSCOPED_APP_SCOPE

    normalized_bundle_id = bundle_id.strip()
    platform = parse_app_client_platform(platform_value)
    app_client = find_app_client_by_bundle_id(
        db,
        bundle_id=normalized_bundle_id,
        platform=platform,
    )

    if app_client is None:
        logger.warning(
            "App scope unresolved bundle_id=%s platform=%s; falling back to marketplace",
            normalized_bundle_id,
            platform.value if platform else "unknown",
        )
        return UNSCOPED_APP_SCOPE

    return AppScope(
        mode=app_client.app_mode,
        restaurant_id=app_client.restaurant_id,
        app_client_id=app_client.id,
        app_key=app_client.key,
        bundle_id=normalized_bundle_id,
        platform=platform,
        status=app_client.status,
    )


def get_default_app_client(db: Session) -> AppClient | None:
    """The marketplace app client that owns header-less customers.

    Looked up by the configured key, falling back to the oldest active
    MARKETPLACE client so a renamed key degrades instead of breaking auth.
    """

    settings = get_settings()
    app_client = db.scalar(
        select(AppClient).where(AppClient.key == settings.default_app_client_key)
    )
    if app_client is not None:
        return app_client

    return db.scalar(
        select(AppClient)
        .where(
            AppClient.app_mode == AppMode.MARKETPLACE,
            AppClient.status == AppClientStatus.ACTIVE,
        )
        .order_by(AppClient.created_at.asc())
        .limit(1)
    )


def ensure_default_app_client(db: Session) -> AppClient:
    """Return the default marketplace app client, creating it when absent.

    A fresh database has no marketplace client, yet customer identity resolves
    to one, so seeding and backfilling both need this guarantee. The caller
    commits.
    """

    existing = get_default_app_client(db)
    if existing is not None:
        return existing

    settings = get_settings()
    app_client = AppClient(
        key=settings.default_app_client_key,
        display_name=DEFAULT_APP_CLIENT_DISPLAY_NAME,
        app_mode=AppMode.MARKETPLACE,
        restaurant_id=None,
        status=AppClientStatus.ACTIVE,
        order_number_prefix="MP",
        branding={BRANDING_PRIMARY_COLOR_KEY: DEFAULT_BRAND_PRIMARY_COLOR},
        config={CONFIG_MINIMUM_SUPPORTED_VERSION_KEY: DEFAULT_MINIMUM_SUPPORTED_VERSION},
    )
    app_client.order_sequence = AppClientOrderSequence(last_value=0)
    db.add(app_client)
    db.flush()
    logger.info("Created default marketplace app client key=%s", app_client.key)
    return app_client


def resolve_identity_app_client_id(db: Session, app_scope: AppScope) -> uuid.UUID:
    """The app client a user account belongs to for this request.

    Distinct from restaurant scoping: that fails open to the whole marketplace
    when a bundle id is missing or unknown, which is fine for browsing but would
    be a hole for identity. Here a caller without a resolvable bundle id (the
    customer web app) is treated as the default marketplace client, so stripping
    the header cannot move an account between apps - it just lands on the same
    scope the web app already uses.

    Raises 503 rather than failing open when no marketplace client exists, since
    guessing an identity scope is worse than refusing to serve.
    """

    if app_scope.app_client_id is not None:
        return app_scope.app_client_id

    default_app_client = get_default_app_client(db)
    if default_app_client is None:
        logger.error(
            "No default app client (key=%s); customer identity cannot be resolved",
            get_settings().default_app_client_key,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="App identity is not configured on this server",
        )
    return default_app_client.id


def get_app_client_for_restaurant(db: Session, *, restaurant_id: uuid.UUID) -> AppClient | None:
    return db.scalar(
        select(AppClient)
        .where(AppClient.restaurant_id == restaurant_id)
        .options(selectinload(AppClient.identifiers))
        .order_by(AppClient.created_at.asc())
    )


def _sync_prod_identifiers(
    db: Session,
    app_client: AppClient,
    *,
    ios_bundle_id: str,
    android_package_name: str,
) -> None:
    """Replace the PROD identifiers when they change, leaving STAGING rows alone.

    They are deleted and re-inserted rather than updated in place so that
    swapping the two values cannot transiently violate the
    (platform, identifier, environment) unique constraint.
    """

    current = {
        identifier.platform: identifier
        for identifier in app_client.identifiers
        if identifier.environment == AppClientEnvironment.PROD
    }
    current_ios = current.get(AppClientPlatform.IOS)
    current_android = current.get(AppClientPlatform.ANDROID)

    if (
        current_ios is not None
        and current_android is not None
        and current_ios.identifier == ios_bundle_id
        and current_android.identifier == android_package_name
    ):
        return

    for identifier in (current_ios, current_android):
        if identifier is not None:
            app_client.identifiers.remove(identifier)
    db.flush()

    app_client.identifiers.extend(
        [
            AppClientIdentifier(
                platform=AppClientPlatform.IOS,
                identifier=ios_bundle_id,
                environment=AppClientEnvironment.PROD,
                is_active=True,
            ),
            AppClientIdentifier(
                platform=AppClientPlatform.ANDROID,
                identifier=android_package_name,
                environment=AppClientEnvironment.PROD,
                is_active=True,
            ),
        ]
    )


def upsert_app_client_for_restaurant(
    db: Session,
    *,
    restaurant: Restaurant,
    payload: AppClientUpsertRequest,
) -> AppClient:
    """Create or update the app client of an existing restaurant.

    Restaurants created before app clients existed simply get one on first save,
    so no restaurant ever needs to be recreated.
    """

    app_client = get_app_client_for_restaurant(db, restaurant_id=restaurant.id)

    validate_app_client_identity_is_available(
        db,
        app_key=payload.app_key,
        ios_bundle_id=payload.ios_bundle_id,
        android_package_name=payload.android_package_name,
        exclude_app_client_id=app_client.id if app_client is not None else None,
    )

    if app_client is None:
        app_client = AppClient(
            key=payload.app_key,
            display_name=restaurant.name,
            app_mode=payload.app_mode,
            restaurant_id=restaurant.id,
            status=AppClientStatus.ACTIVE,
            order_number_prefix=payload.order_number_prefix,
            branding={},
            config={},
        )
        app_client.order_sequence = AppClientOrderSequence(last_value=0)
        db.add(app_client)
    else:
        app_client.key = payload.app_key
        app_client.app_mode = payload.app_mode
        app_client.order_number_prefix = payload.order_number_prefix
        if app_client.order_sequence is None:
            app_client.order_sequence = AppClientOrderSequence(last_value=0)

    # Unknown branding/config keys set by other tooling are preserved.
    app_client.branding = {
        **(app_client.branding or {}),
        BRANDING_PRIMARY_COLOR_KEY: payload.brand_primary_color,
    }
    app_client.config = {
        **(app_client.config or {}),
        CONFIG_MINIMUM_SUPPORTED_VERSION_KEY: payload.minimum_supported_version,
    }

    db.flush()
    _sync_prod_identifiers(
        db,
        app_client,
        ios_bundle_id=payload.ios_bundle_id,
        android_package_name=payload.android_package_name,
    )
    return app_client


def build_app_config_response(app_client: AppClient, *, bundle_id: str) -> AppConfigResponse:
    """Flatten an app client into the startup payload the mobile app consumes.

    Records written before a field existed fall back to defaults so that a build
    always receives a usable configuration.
    """

    branding = dict(app_client.branding or {})
    branding.setdefault(BRANDING_PRIMARY_COLOR_KEY, DEFAULT_BRAND_PRIMARY_COLOR)

    return AppConfigResponse(
        app_client_id=app_client.id,
        app_key=app_client.key,
        app_mode=app_client.app_mode,
        restaurant_id=app_client.restaurant_id,
        display_name=app_client.display_name,
        branding=branding,
        order_prefix=app_client.order_number_prefix,
        minimum_supported_version=(
            app_client.minimum_supported_version or DEFAULT_MINIMUM_SUPPORTED_VERSION
        ),
        bundle_id=bundle_id.strip(),
    )


@dataclass
class AppClientBackfillSummary:
    created: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return len(self.created) + len(self.completed)


def backfill_app_clients(db: Session) -> AppClientBackfillSummary:
    """Give every app client a complete configuration.

    Restaurants without an app client get one created. Every app client is then
    completed, including marketplace clients that are not linked to a restaurant.

    Idempotent and non-destructive: values that are already set are never
    overwritten, only missing ones are filled in. Safe to run repeatedly.
    """

    summary = AppClientBackfillSummary()

    # A marketplace client must exist: customer identity resolves to it when a
    # request carries no bundle id, and nothing else in the codebase creates one.
    ensure_default_app_client(db)

    restaurants = db.scalars(select(Restaurant).order_by(Restaurant.created_at.asc())).all()
    for restaurant in restaurants:
        if get_app_client_for_restaurant(db, restaurant_id=restaurant.id) is not None:
            continue

        identity = resolve_app_client_identity(db, restaurant_name=restaurant.name)
        db.add(
            create_app_client(
                restaurant_id=restaurant.id,
                display_name=restaurant.name,
                identity=identity,
            )
        )
        db.flush()
        summary.created.append(f"{restaurant.name} -> {identity.app_key}")

    app_clients = db.scalars(select(AppClient).order_by(AppClient.created_at.asc())).all()
    for app_client in app_clients:
        filled: list[str] = []

        if not app_client.brand_primary_color:
            app_client.branding = {
                **(app_client.branding or {}),
                BRANDING_PRIMARY_COLOR_KEY: DEFAULT_BRAND_PRIMARY_COLOR,
            }
            filled.append("brand_primary_color")

        if not app_client.minimum_supported_version:
            app_client.config = {
                **(app_client.config or {}),
                CONFIG_MINIMUM_SUPPORTED_VERSION_KEY: DEFAULT_MINIMUM_SUPPORTED_VERSION,
            }
            filled.append("minimum_supported_version")

        if app_client.order_sequence is None:
            app_client.order_sequence = AppClientOrderSequence(last_value=0)
            filled.append("order_sequence")

        missing_platforms = [
            platform
            for platform in (AppClientPlatform.IOS, AppClientPlatform.ANDROID)
            if not any(
                identifier.platform == platform and identifier.environment == AppClientEnvironment.PROD
                for identifier in app_client.identifiers
            )
        ]
        if missing_platforms:
            # Reuse whichever platform identifier already exists so both
            # platforms stay aligned; otherwise derive one from the app key.
            fallback = app_client.ios_bundle_id or app_client.android_package_name
            bundle_id = fallback or _generate_unique_bundle_id(db, app_client.key)
            for platform in missing_platforms:
                app_client.identifiers.append(
                    AppClientIdentifier(
                        platform=platform,
                        identifier=bundle_id,
                        environment=AppClientEnvironment.PROD,
                        is_active=True,
                    )
                )
                filled.append(
                    "ios_bundle_id" if platform == AppClientPlatform.IOS else "android_package_name"
                )

        if filled:
            db.flush()
            summary.completed.append(f"{app_client.key} ({', '.join(filled)})")
        else:
            summary.unchanged.append(app_client.key)

    return summary
