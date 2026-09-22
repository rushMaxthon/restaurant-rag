from fastapi import APIRouter

from app.api.admin import router as admin_router
from app.api.app_clients import router as app_clients_router
from app.api.app_config import router as app_config_router
from app.api.preference_admin import router as preference_admin_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.favorites import router as favorites_router
from app.api.generated_combos import router as generated_combos_router
from app.api.insights import router as insights_router
from app.api.marketing import router as marketing_router
from app.api.menu_items import router as menu_items_router
from app.api.notifications import router as notifications_router
from app.api.orders import router as orders_router
from app.api.payments import router as payments_router
from app.api.short_links import router as short_links_router
from app.api.personalized_offers import router as personalized_offers_router
from app.api.preferences import router as preferences_router
from app.api.profile import router as profile_router
from app.api.recommendations import router as recommendations_router
from app.api.reports import router as reports_router
from app.api.restaurants import router as restaurants_router
from app.api.suggestions import router as suggestions_router
from app.api.whatsapp import router as whatsapp_router

api_router = APIRouter()
api_router.include_router(admin_router)
api_router.include_router(app_clients_router)
api_router.include_router(app_config_router)
api_router.include_router(preference_admin_router)
api_router.include_router(auth_router)
api_router.include_router(chat_router)
api_router.include_router(favorites_router)
api_router.include_router(generated_combos_router)
api_router.include_router(insights_router)
api_router.include_router(restaurants_router)
api_router.include_router(marketing_router)
api_router.include_router(menu_items_router)
api_router.include_router(notifications_router)
api_router.include_router(orders_router)
api_router.include_router(payments_router)
api_router.include_router(short_links_router)
api_router.include_router(personalized_offers_router)
api_router.include_router(preferences_router)
api_router.include_router(profile_router)
api_router.include_router(recommendations_router)
api_router.include_router(reports_router)
api_router.include_router(suggestions_router)
api_router.include_router(whatsapp_router)

__all__ = ["api_router"]
