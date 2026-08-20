from __future__ import annotations

import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import (
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferGenerationReason,
    PersonalizedOfferSource,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.personalized_offer import GeneratedOffer, GeneratedOfferUserMatch
from app.models.user import User
from app.main import app
from app.services.auth import require_admin
from app.services.ai_offer_generation import (
    AIOfferCandidate,
    AIOfferGenerationSummary,
    _build_offer_candidate_for_user,
    _extract_json_payload,
    _refresh_reason_for_existing_offer,
    _generate_payload_with_llm,
    _normalize_discount_type,
    _offer_has_current_match,
    _validate_or_fallback_payload,
)


def make_candidate() -> AIOfferCandidate:
    return AIOfferCandidate(
        offer_type=PersonalizedOfferType.FAVORITE_ITEM,
        audience_type=PersonalizedOfferAudience.ACTIVE_USERS,
        generation_reason=PersonalizedOfferGenerationReason.REPEATED_ORDER,
        restaurant_id=uuid.uuid4(),
        restaurant_name="Dragon Wok",
        restaurant_slug="dragon-wok",
        restaurant_location_id=uuid.uuid4(),
        restaurant_location_name="CG Road",
        applicable_item_id=uuid.uuid4(),
        applicable_item_name="Kung Pao Chicken",
        applicable_category="Main Course",
        applicable_cuisine="Chinese",
        score=Decimal("900.00"),
        target_type="ITEM",
        target_id=str(uuid.uuid4()),
        fallback_title="Save on your favorite pick",
        fallback_subtitle="Built around your repeat orders.",
        fallback_cta="Order Again",
        fallback_reason="Repeated item detected",
        fallback_discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
        fallback_discount_value=Decimal("10.00"),
        fallback_minimum_order_amount=Decimal("149.00"),
        fallback_max_discount_amount=Decimal("100.00"),
    )


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        full_name="Offer Tester",
        email="offer-tester@example.com",
        phone_number=None,
        hashed_password="hash",
        role=UserRole.CUSTOMER,
        is_active=True,
        is_verified=True,
        default_address=None,
    )


class AIOfferGenerationTests(unittest.TestCase):
    def test_generation_summary_to_dict_handles_slots_dataclass(self) -> None:
        summary = AIOfferGenerationSummary(
            users_scanned=4,
            offers_generated=2,
            offers_replaced=1,
            fallbacks_used=1,
            validation_failures=0,
            skipped_users=2,
            llm_failures=1,
            elapsed_ms=123,
        )
        self.assertEqual(
            summary.to_dict(),
            {
                "users_scanned": 4,
                "offers_generated": 2,
                "offers_replaced": 1,
                "fallbacks_used": 1,
                "validation_failures": 0,
                "skipped_users": 2,
                "llm_failures": 1,
                "elapsed_ms": 123,
            },
        )

    def test_extract_json_payload_supports_wrapped_json(self) -> None:
        payload = _extract_json_payload('prefix {"title":"Hi","subtitle":"There","discount_type":"flat","discount_value":40,"minimum_order":199,"cta":"Order","reason":"Repeat"} suffix')
        self.assertEqual(payload["title"], "Hi")

    def test_normalize_discount_type_maps_free_delivery(self) -> None:
        self.assertEqual(
            _normalize_discount_type("free_delivery"),
            PersonalizedOfferDiscountType.FREE_DELIVERY,
        )

    def test_validate_or_fallback_accepts_safe_payload(self) -> None:
        payload, fallback_used, fallback_reason = _validate_or_fallback_payload(
            make_candidate(),
            llm_payload={
                "title": "Pizza night is back",
                "subtitle": "A safe repeat-order offer just for you.",
                "discount_type": "percentage",
                "discount_value": 15,
                "minimum_order": 199,
                "cta": "Order Now",
                "reason": "Repeat item behavior",
            },
        )
        self.assertFalse(fallback_used)
        self.assertIsNone(fallback_reason)
        self.assertEqual(payload["discount_type"], "PERCENTAGE")

    def test_validate_or_fallback_rejects_unsafe_discount(self) -> None:
        payload, fallback_used, fallback_reason = _validate_or_fallback_payload(
            make_candidate(),
            llm_payload={
                "title": "Too much",
                "subtitle": "Unsafe discount",
                "discount_type": "percentage",
                "discount_value": 90,
                "minimum_order": 199,
                "cta": "Order Now",
                "reason": "Unsafe",
            },
        )
        self.assertTrue(fallback_used)
        self.assertEqual(payload["title"], make_candidate().fallback_title)
        self.assertIsNotNone(fallback_reason)

    @patch("app.services.ai_offer_generation.GENERATE_CLIENT")
    def test_generate_payload_with_llm_times_out_to_fallback(self, mock_client: Mock) -> None:
        mock_client.post.side_effect = httpx.ReadTimeout("timed out")
        payload, fallback_used, fallback_reason = _generate_payload_with_llm(make_candidate(), make_user())
        self.assertTrue(fallback_used)
        self.assertIsNotNone(fallback_reason)
        self.assertEqual(payload["discount_type"], "PERCENTAGE")

    @patch("app.services.ai_offer_generation.GENERATE_CLIENT")
    def test_generate_payload_with_llm_accepts_valid_json(self, mock_client: Mock) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": '{"title":"Welcome back","subtitle":"Safe savings on your next meal.","discount_type":"flat","discount_value":40,"minimum_order":199,"cta":"Order Now","reason":"Inactive user"}'
        }
        mock_client.post.return_value = response

        payload, fallback_used, fallback_reason = _generate_payload_with_llm(make_candidate(), make_user())
        self.assertFalse(fallback_used)
        self.assertIsNone(fallback_reason)
        self.assertEqual(payload["discount_type"], "FLAT")

    def test_offer_has_current_match_detects_live_user_match(self) -> None:
        user = make_user()
        offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=user.id,
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.ORDER_HISTORY_MATCH,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            generated_title="Fallback",
            generated_subtitle="Fallback copy",
            generated_badge="Offer",
            generated_cta_label="Explore",
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value=Decimal("25.00"),
            minimum_order_amount=Decimal("199.00"),
            valid_for_days=7,
            score=Decimal("760.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=datetime.now(UTC) - timedelta(hours=1),
            expires_at=datetime.now(UTC) + timedelta(days=2),
        )
        offer.user_matches = [
            GeneratedOfferUserMatch(
                generated_offer_id=offer.id,
                user_id=user.id,
                matched_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
                score=Decimal("760.00"),
                rank=1,
                is_current=True,
            )
        ]
        self.assertTrue(_offer_has_current_match(offer, user_id=user.id))

    def test_refresh_reason_skips_when_offer_is_still_fresh(self) -> None:
        user = make_user()
        now = datetime.now(UTC)
        offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=user.id,
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.ORDER_HISTORY_MATCH,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            generated_title="Fallback",
            generated_subtitle="Fallback copy",
            generated_badge="Offer",
            generated_cta_label="Explore",
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value=Decimal("25.00"),
            minimum_order_amount=Decimal("199.00"),
            valid_for_days=7,
            score=Decimal("760.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=now - timedelta(hours=1),
            expires_at=now + timedelta(days=2),
            conversion_count=0,
        )
        offer.user_matches = [
            GeneratedOfferUserMatch(
                generated_offer_id=offer.id,
                user_id=user.id,
                matched_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
                score=Decimal("760.00"),
                rank=1,
                is_current=True,
            )
        ]
        self.assertIsNone(
            _refresh_reason_for_existing_offer(
                offer,
                user_id=user.id,
                now=now,
                force_refresh=False,
            )
        )

    def test_refresh_reason_requires_regeneration_for_converted_offer(self) -> None:
        user = make_user()
        now = datetime.now(UTC)
        offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=user.id,
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.ORDER_HISTORY_MATCH,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            generated_title="Fallback",
            generated_subtitle="Fallback copy",
            generated_badge="Offer",
            generated_cta_label="Explore",
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value=Decimal("25.00"),
            minimum_order_amount=Decimal("199.00"),
            valid_for_days=7,
            score=Decimal("760.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=now - timedelta(hours=1),
            expires_at=now + timedelta(days=2),
            conversion_count=1,
        )
        offer.user_matches = [
            GeneratedOfferUserMatch(
                generated_offer_id=offer.id,
                user_id=user.id,
                matched_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
                score=Decimal("760.00"),
                rank=1,
                is_current=True,
            )
        ]
        self.assertEqual(
            _refresh_reason_for_existing_offer(
                offer,
                user_id=user.id,
                now=now,
                force_refresh=False,
            ),
            "offer_already_converted",
        )

    def test_refresh_reason_allows_force_refresh_for_manual_trigger(self) -> None:
        user = make_user()
        now = datetime.now(UTC)
        offer = GeneratedOffer(
            id=uuid.uuid4(),
            template_offer_id=None,
            generated_for_user_id=user.id,
            restaurant_id=uuid.uuid4(),
            restaurant_location_id=None,
            applicable_item_id=None,
            generated_combo_id=None,
            source=PersonalizedOfferSource.AI_GENERATED,
            generation_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
            state=PersonalizedOfferState.ACTIVE,
            offer_type=PersonalizedOfferType.ORDER_HISTORY_MATCH,
            audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
            generated_title="Fallback",
            generated_subtitle="Fallback copy",
            generated_badge="Offer",
            generated_cta_label="Explore",
            discount_type=PersonalizedOfferDiscountType.FLAT,
            discount_value=Decimal("25.00"),
            minimum_order_amount=Decimal("199.00"),
            valid_for_days=7,
            score=Decimal("760.00"),
            eligible_user_count=1,
            business_metadata={},
            starts_at=now - timedelta(hours=1),
            expires_at=now + timedelta(days=2),
            conversion_count=0,
        )
        offer.user_matches = [
            GeneratedOfferUserMatch(
                generated_offer_id=offer.id,
                user_id=user.id,
                matched_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
                score=Decimal("760.00"),
                rank=1,
                is_current=True,
            )
        ]
        self.assertEqual(
            _refresh_reason_for_existing_offer(
                offer,
                user_id=user.id,
                now=now,
                force_refresh=True,
            ),
            "force_refresh_requested",
        )

    @patch("app.services.ai_offer_generation._load_order_insights")
    @patch("app.services.ai_offer_generation._load_user_preferences")
    def test_build_offer_candidate_skips_users_without_paid_order_history(
        self,
        mock_load_user_preferences: Mock,
        mock_load_order_insights: Mock,
    ) -> None:
        user = make_user()
        db = Mock()
        mock_load_user_preferences.return_value = None
        mock_load_order_insights.return_value = Mock(latest_order_at=None)

        candidate = _build_offer_candidate_for_user(db, user)

        self.assertIsNone(candidate)


class AdminAIOfferTriggerApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.admin_user = User(
            id=uuid.uuid4(),
            full_name="Admin Tester",
            email="admin@example.com",
            phone_number=None,
            hashed_password="hash",
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
            default_address=None,
        )
        app.dependency_overrides[require_admin] = lambda: self.admin_user

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()

    @patch("app.api.admin.generate_ai_offers_task.delay")
    def test_trigger_ai_offer_generation_queues_task_when_queue_only(self, mock_delay: Mock) -> None:
        mock_delay.return_value = Mock(id="task-123")
        response = self.client.post(
            "/api/admin/offers/generate-ai",
            json={"force_refresh": True, "user_limit": 3, "queue_only": True},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["task_id"], "task-123")
        self.assertTrue(payload["queued"])
        self.assertFalse(payload["ready"])
        mock_delay.assert_called_once_with(
            user_limit=3,
            batch_size=None,
            force_refresh=True,
            allow_disabled=True,
        )

    @patch("app.api.admin.generate_ai_offers_task.apply")
    def test_trigger_ai_offer_generation_runs_inline_by_default(self, mock_apply: Mock) -> None:
        result = Mock()
        result.id = "task-inline"
        result.state = "SUCCESS"
        result.successful.return_value = True
        result.result = {
            "users_scanned": 4,
            "offers_generated": 2,
            "offers_replaced": 1,
            "fallbacks_used": 0,
            "validation_failures": 0,
            "skipped_users": 2,
            "llm_failures": 0,
            "elapsed_ms": 180,
        }
        mock_apply.return_value = result
        response = self.client.post(
            "/api/admin/offers/generate-ai",
            json={"force_refresh": False},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["queued"])
        self.assertTrue(payload["ready"])
        self.assertTrue(payload["successful"])
        self.assertEqual(payload["summary"]["offers_generated"], 2)
        mock_apply.assert_called_once_with(
            kwargs={
                "user_limit": None,
                "batch_size": None,
                "force_refresh": False,
                "allow_disabled": True,
            }
        )

    @patch("app.api.admin.celery_app.AsyncResult")
    def test_get_ai_offer_generation_status_returns_summary(self, mock_async_result: Mock) -> None:
        result = Mock()
        result.state = "SUCCESS"
        result.ready.return_value = True
        result.successful.return_value = True
        result.result = {
            "users_scanned": 4,
            "offers_generated": 3,
            "offers_replaced": 1,
            "fallbacks_used": 1,
            "validation_failures": 0,
            "skipped_users": 1,
            "llm_failures": 1,
            "elapsed_ms": 250,
        }
        mock_async_result.return_value = result

        response = self.client.get("/api/admin/offers/generate-ai/task-123")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ready"])
        self.assertTrue(payload["successful"])
        self.assertEqual(payload["summary"]["offers_generated"], 3)


if __name__ == "__main__":
    unittest.main()
