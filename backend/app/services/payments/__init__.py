"""Payment provider abstraction and orchestration.

Card payments settle through Stripe; COD settles through nobody. Adding a
gateway later means implementing :class:`PaymentProvider` and registering it —
the order flow, webhook log and transaction table are already provider-neutral.
"""

from app.services.payments.base import (
    PaymentIntentResult,
    PaymentProvider,
    PaymentProviderError,
    WebhookEvent,
    WebhookVerificationError,
)
from app.services.payments.registry import (
    COD_PROVIDER_NAME,
    SUPPORTED_PAYMENT_METHODS,
    available_payment_methods,
    is_method_supported,
    provider_name_for,
    resolve_provider,
)
from app.services.payments.service import (
    cancel_payment,
    create_payment_intent,
    get_payment_status,
    handle_stripe_webhook,
    payment_config,
    reap_expired_unpaid_orders,
)

__all__ = [
    "COD_PROVIDER_NAME",
    "PaymentIntentResult",
    "PaymentProvider",
    "PaymentProviderError",
    "SUPPORTED_PAYMENT_METHODS",
    "WebhookEvent",
    "WebhookVerificationError",
    "available_payment_methods",
    "cancel_payment",
    "create_payment_intent",
    "get_payment_status",
    "handle_stripe_webhook",
    "is_method_supported",
    "payment_config",
    "provider_name_for",
    "reap_expired_unpaid_orders",
    "resolve_provider",
]
