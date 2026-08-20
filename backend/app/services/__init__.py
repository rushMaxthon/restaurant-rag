from app.services.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    get_current_user_optional,
    get_owner_restaurant_id,
    hash_password,
    require_admin,
    require_customer,
    require_owner,
    resolve_owner_restaurant_id,
    verify_password,
)
from app.services.orders import create_order, get_order_for_user, list_orders, update_order_status
from app.services.rag import get_chat_history, handle_chat_message
from app.services.recommendations import (
    get_recommendations_for_request,
    get_recommendations_for_user,
    get_user_preferences_response,
    upsert_user_preferences,
)

__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "authenticate_user",
    "get_current_user",
    "get_current_user_optional",
    "get_owner_restaurant_id",
    "require_admin",
    "require_customer",
    "require_owner",
    "resolve_owner_restaurant_id",
    "create_order",
    "list_orders",
    "get_order_for_user",
    "update_order_status",
    "handle_chat_message",
    "get_chat_history",
    "get_user_preferences_response",
    "upsert_user_preferences",
    "get_recommendations_for_request",
    "get_recommendations_for_user",
]
