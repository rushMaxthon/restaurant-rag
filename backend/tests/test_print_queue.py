"""The queue's three promises, against a real database.

Postgres rather than a stub, because two of the three promises ARE Postgres:
the partial unique index that makes automatic printing idempotent, and the
`FOR UPDATE SKIP LOCKED` that stops two polls being served the same ticket.
Asserting them against a fake would be asserting that the fake agrees with
itself.

The first test here exists because of a bug found by running the thing, not by
reading it. `enqueue_for_order` called `db.add(job)` and then flushed inside a
savepoint, which looks like containment and is not: the object stays pending on
the OUTER session, so rolling the savepoint back undoes the INSERT without
discarding the object, and the next flush retries exactly the insert the index
just refused. The session ends in `PendingRollbackError` — which means the
ORDER's commit fails.

So a duplicate ticket would have cost a customer their order. That is the one
outcome this module promises is impossible, and it was live until a second
enqueue was actually attempted.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from unittest import mock
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.base import Base  # noqa: E402
from app.models.enums import (  # noqa: E402
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PrinterTransport,
    PrintJobKind,
    PrintJobSource,
    PrintJobStatus,
    UserRole,
)
from app.models.order import Order  # noqa: E402
from app.models.menu_item import MenuItem  # noqa: E402
from app.models.order_item import OrderItem  # noqa: E402
from app.models.print_agent import PrintAgent, Printer, PrintJob  # noqa: E402
from app.models.restaurant import Restaurant  # noqa: E402
from app.models.restaurant_location import RestaurantLocation  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.print.queue import (  # noqa: E402
    ack_job,
    claim_jobs,
    enqueue_for_order,
    printers_for,
)

settings = get_settings()
TEST_DB_NAME = os.environ.get("PRINT_TEST_DB", "restaurant_rag_print_test")


def _admin_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/postgres"
    )


def _test_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{TEST_DB_NAME}"
    )


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            engine.dispose()


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class PrintQueueTests(unittest.TestCase):
    engine = None
    session_factory = None

    @classmethod
    def setUpClass(cls) -> None:
        admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin.dispose()

        cls.engine = create_engine(_test_url())
        with cls.engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
        Base.metadata.create_all(cls.engine)
        # `create_all` does not build a partial index with a predicate over
        # enum columns, which is where the whole idempotency guarantee lives.
        # Created here exactly as `0074_print_agents` creates it, so these
        # tests exercise the real constraint rather than a weaker one.
        with cls.engine.connect() as connection:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_print_jobs_auto_once "
                    "ON print_jobs (printer_id, order_id, kind) "
                    "WHERE source = 'AUTO' AND status <> 'FAILED'"
                )
            )
            connection.commit()
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin.dispose()

    def setUp(self) -> None:
        self.session = self.session_factory()
        self.addCleanup(self.session.close)
        # Printing on, through the ENVIRONMENT and the settings cache rather
        # than by assigning to a `Settings` instance.
        #
        # Assigning worked in isolation and failed in the full suite, which is
        # the worst way for a test to be wrong. `get_settings` is
        # `lru_cache`d, and `test_delivery_dispatch` calls
        # `get_settings.cache_clear()` — so by the time these ran, the object
        # this module imported at the top was no longer the one `claim_jobs`
        # reads, and the mutation landed on nothing. Same device the delivery
        # tests use, for the same reason.
        self._flag = mock.patch.dict(os.environ, {"ENABLE_AUTO_PRINT": "true"})
        self._flag.start()
        self.addCleanup(self._flag.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self._seed()

    def tearDown(self) -> None:
        self.session.rollback()
        for table in ("print_jobs", "printers", "print_agents", "order_items", "orders"):
            self.session.execute(text(f"TRUNCATE {table} CASCADE"))
        self.session.commit()

    def _seed(self) -> None:
        session = self.session
        self.restaurant = session.scalars(select(Restaurant)).first()
        if self.restaurant is None:
            # A restaurant needs its owner: `restaurants.owner_id` is NOT
            # NULL, and one owner belongs to exactly one restaurant.
            owner = User(
                id=uuid.uuid4(),
                full_name="Bhagwati Owner",
                email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                role=UserRole.OWNER,
            )
            session.add(owner)
            session.flush()
            self.restaurant = Restaurant(
                id=uuid.uuid4(),
                owner_id=owner.id,
                name="Bhagwati Bakery",
                slug=f"bb-{uuid.uuid4().hex[:8]}",
                cuisine_type="Bakery",
                address_line_1="Katargam",
                city="Surat",
                state="Gujarat",
                postal_code="395004",
                # So a bill renders with the symbol these tests were written
                # against rather than the model's USD default.
                currency="INR",
            )
            session.add(self.restaurant)
            session.flush()
            self.location = RestaurantLocation(
                id=uuid.uuid4(),
                restaurant_id=self.restaurant.id,
                branch_name="Main Branch",
                address_line_1="Katargam",
                city="Surat",
                state="Gujarat",
                postal_code="395004",
            )
            session.add(self.location)
            self.customer = User(
                id=uuid.uuid4(),
                full_name="Asha Patel",
                email=f"asha-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                role=UserRole.CUSTOMER,
            )
            session.add(self.customer)
            session.commit()
        else:
            self.location = session.scalars(select(RestaurantLocation)).first()
            self.customer = session.scalars(
                select(User).where(User.role == UserRole.CUSTOMER)
            ).first()

        # `order_items.menu_item_id` is NOT NULL, so a line needs a dish even
        # though the ticket reads the name from the snapshot rather than the
        # live row.
        self.dish = session.scalars(select(MenuItem)).first()
        if self.dish is None:
            self.dish = MenuItem(
                id=uuid.uuid4(),
                restaurant_id=self.restaurant.id,
                restaurant_location_id=self.location.id,
                name="Brown Bread",
                category="Bakery",
                price=Decimal("50.00"),
            )
            session.add(self.dish)
            session.commit()

        self.agent = PrintAgent(
            restaurant_id=self.restaurant.id,
            restaurant_location_id=self.location.id,
            name="Kitchen PC",
            token_hash=uuid.uuid4().hex * 2,
        )
        session.add(self.agent)
        session.flush()
        self.printer = Printer(
            print_agent_id=self.agent.id,
            name="Kitchen",
            transport=PrinterTransport.TCP,
            host="192.168.1.50",
            port=9100,
            paper_width_chars=48,
            docket_kinds=[PrintJobKind.KITCHEN_DOCKET.value, PrintJobKind.VOID_SLIP.value],
        )
        session.add(self.printer)
        self.order = self._make_order()
        session.commit()

    def _make_order(self) -> Order:
        order = Order(
            id=uuid.uuid4(),
            customer_id=self.customer.id,
            restaurant_id=self.restaurant.id,
            restaurant_location_id=self.location.id,
            status=OrderStatus.PLACED,
            payment_status=PaymentStatus.PAID,
            payment_method=PaymentMethod.CARD,
            fulfillment_type=OrderFulfillmentType.PICKUP,
            schedule_type=OrderScheduleType.ASAP,
            scheduled_at=datetime.now(UTC),
            subtotal=Decimal("100.00"),
            total_amount=Decimal("120.25"),
            delivery_address="Main Branch - collection",
            contact_name="Asha Patel",
            contact_phone="9825322860",
        )
        self.session.add(order)
        self.session.flush()
        self.session.add(
            OrderItem(
                id=uuid.uuid4(),
                order_id=order.id,
                menu_item_id=self.dish.id,
                item_name_snapshot="Brown Bread",
                quantity=2,
                base_unit_price=Decimal("50.00"),
                unit_price=Decimal("50.00"),
                total_price=Decimal("100.00"),
                selected_options_snapshot=[],
            )
        )
        self.session.flush()
        return order

    def _auto_dockets(self) -> int:
        return self.session.execute(
            text(
                "select count(*) from print_jobs where order_id = :o "
                "and kind = 'KITCHEN_DOCKET' and source = 'AUTO'"
            ),
            {"o": self.order.id},
        ).scalar()

    # --- the regression -----------------------------------------------------

    def test_a_second_enqueue_writes_nothing_and_leaves_the_session_usable(self) -> None:
        """Both halves, because the second one was the dangerous bug.

        The index refusing the duplicate was always going to work. What did
        not work was recovering from it: the failed object stayed pending, the
        next flush retried it, and the session went to
        `PendingRollbackError` - so the ORDER could no longer be committed. A
        duplicate ticket cost a customer their order.
        """

        first = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        self.assertEqual(len(first), 1)
        self.assertEqual(self._auto_dockets(), 1)

        for attempt in range(3):
            again = enqueue_for_order(
                self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET
            )
            self.session.commit()
            self.assertEqual(again, [], f"attempt {attempt + 2} created a job")
            self.assertEqual(self._auto_dockets(), 1)

        # The half that was broken: the caller's transaction still works.
        self.order.contact_name = "Asha P"
        self.session.add(self.order)
        self.session.commit()
        self.assertEqual(
            self.session.get(Order, self.order.id).contact_name,
            "Asha P",
            "the order could not be committed after a duplicate ticket",
        )

    def test_a_manual_reprint_is_deliberately_unconstrained(self) -> None:
        # Pressing Reprint twice should print twice. That is how somebody
        # checks whether the first copy was a fluke.
        enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        for _ in range(2):
            made = enqueue_for_order(
                self.session,
                self.order,
                kind=PrintJobKind.KITCHEN_DOCKET,
                source=PrintJobSource.MANUAL,
            )
            self.session.commit()
            self.assertEqual(len(made), 1)
        self.assertEqual(self._auto_dockets(), 1)

    def test_a_failed_ticket_can_be_queued_again(self) -> None:
        # Excluded from the index on purpose: a printer that was out of paper
        # must not block the order from ever printing.
        [job] = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        ack_job(self.session, self.agent, job.id, printed=False, error="Out of paper")
        again = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        self.assertEqual(len(again), 1)

    # --- routing ------------------------------------------------------------

    def test_a_printer_only_receives_the_kinds_it_subscribes_to(self) -> None:
        # The kitchen printer here takes dockets and voids, not bills. This is
        # what lets one PC drive a kitchen printer and a counter printer
        # without the agent branching on which is which.
        self.assertEqual(
            [p.name for p in printers_for(
                self.session,
                restaurant_location_id=self.location.id,
                kind=PrintJobKind.KITCHEN_DOCKET,
            )],
            ["Kitchen"],
        )
        self.assertEqual(
            printers_for(
                self.session,
                restaurant_location_id=self.location.id,
                kind=PrintJobKind.CUSTOMER_BILL,
            ),
            [],
        )
        self.assertEqual(
            enqueue_for_order(self.session, self.order, kind=PrintJobKind.CUSTOMER_BILL), []
        )

    def test_a_disabled_printer_receives_nothing(self) -> None:
        self.printer.is_enabled = False
        self.session.commit()
        self.assertEqual(
            enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET), []
        )

    def test_a_disabled_agent_takes_its_printers_with_it(self) -> None:
        # Deactivating the PC must stop its printers, or an agent revoked for
        # a reason keeps printing until somebody finds every printer row.
        self.agent.is_enabled = False
        self.session.commit()
        self.assertEqual(
            enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET), []
        )

    def test_another_branch_printer_is_not_used(self) -> None:
        # The scope that matters: a ticket for Surat must not appear in
        # Ahmedabad.
        other = RestaurantLocation(
            id=uuid.uuid4(),
            restaurant_id=self.restaurant.id,
            branch_name="Second Branch",
            address_line_1="Adajan",
            city="Surat",
            state="Gujarat",
            postal_code="395009",
        )
        self.session.add(other)
        self.session.commit()
        self.assertEqual(
            printers_for(
                self.session,
                restaurant_location_id=other.id,
                kind=PrintJobKind.KITCHEN_DOCKET,
            ),
            [],
        )

    # --- claiming -----------------------------------------------------------

    def test_claiming_hands_out_queued_work_oldest_first(self) -> None:
        enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        claimed = claim_jobs(self.session, self.agent)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0].status, PrintJobStatus.CLAIMED)
        self.assertEqual(claimed[0].attempts, 1)
        # And a second poll gets nothing, because the lease is live.
        self.assertEqual(claim_jobs(self.session, self.agent), [])

    def test_an_expired_lease_is_served_again(self) -> None:
        # The whole of the crash recovery, and it needs no sweeper: an agent
        # that died mid-print hands the ticket back by doing nothing.
        [job] = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        claim_jobs(self.session, self.agent)
        job.claimed_at = datetime.now(UTC) - timedelta(
            seconds=get_settings().print_job_claim_lease_seconds + 30
        )
        self.session.add(job)
        self.session.commit()
        again = claim_jobs(self.session, self.agent)
        self.assertEqual([j.id for j in again], [job.id])
        self.assertEqual(again[0].attempts, 2, "a retry should be visible as one")

    def test_nothing_is_served_while_the_flag_is_off(self) -> None:
        # The dry run. Rows are written and visible to the owner; no agent is
        # given them. Paper is not recallable, so this is the posture.
        enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        with mock.patch.dict(os.environ, {"ENABLE_AUTO_PRINT": "false"}):
            get_settings.cache_clear()
            self.assertEqual(claim_jobs(self.session, self.agent), [])
        get_settings.cache_clear()
        self.assertEqual(
            self._auto_dockets(), 1, "the job should still exist to be inspected"
        )

    # --- acknowledging ------------------------------------------------------

    def test_acking_printed_closes_the_job_and_dates_the_printer(self) -> None:
        [job] = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        claim_jobs(self.session, self.agent)
        acked = ack_job(self.session, self.agent, job.id, printed=True)
        self.assertEqual(acked.status, PrintJobStatus.PRINTED)
        self.assertIsNotNone(acked.printed_at)
        self.assertIsNotNone(self.printer.last_printed_at)
        self.assertIsNone(self.printer.last_error)

    def test_acking_twice_changes_nothing(self) -> None:
        # Not a client bug: the agent keeps a ledger of printed ids and
        # re-acks a redelivery, which is how exactly-once paper works.
        [job] = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        first = ack_job(self.session, self.agent, job.id, printed=True)
        printed_at = first.printed_at
        second = ack_job(self.session, self.agent, job.id, printed=True)
        self.assertEqual(second.status, PrintJobStatus.PRINTED)
        self.assertEqual(second.printed_at, printed_at, "the first print time stands")

    def test_a_failure_carries_a_sentence_the_owner_can_act_on(self) -> None:
        [job] = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        ack_job(
            self.session,
            self.agent,
            job.id,
            printed=False,
            error="The printer at 192.168.1.50 did not answer. Check it is switched on.",
        )
        self.assertEqual(job.status, PrintJobStatus.FAILED)
        self.assertIn("switched on", self.printer.last_error)

    def test_another_agents_job_is_invisible(self) -> None:
        # Returns None rather than raising, so the route answers 404 - a
        # client learns nothing about work that is not its own, including
        # whether it exists. The order board's rule.
        [job] = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        intruder = PrintAgent(
            restaurant_id=self.restaurant.id,
            restaurant_location_id=self.location.id,
            name="Someone else's PC",
            token_hash=uuid.uuid4().hex * 2,
        )
        self.session.add(intruder)
        self.session.commit()
        self.assertIsNone(ack_job(self.session, intruder, job.id, printed=True))
        self.assertEqual(job.status, PrintJobStatus.QUEUED)

    # --- the document -------------------------------------------------------

    def test_the_rendered_ticket_is_stored_on_the_job(self) -> None:
        # So a reprint reproduces what the kitchen saw, even if the menu has
        # changed since. Rendering again would quietly produce a different
        # ticket and nobody would know which one the cook worked from.
        [job] = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        stored = self.session.get(PrintJob, job.id).document
        self.assertEqual(stored["width"], 48)
        self.assertEqual(stored["kind"], "KITCHEN_DOCKET")
        text_values = [line.get("v") for line in stored["lines"]]
        self.assertIn("Brown Bread", " ".join(v for v in text_values if v))

    def test_the_document_is_laid_out_for_that_printer_width(self) -> None:
        self.printer.paper_width_chars = 32
        self.session.commit()
        [job] = enqueue_for_order(self.session, self.order, kind=PrintJobKind.KITCHEN_DOCKET)
        self.session.commit()
        self.assertEqual(job.document["width"], 32)


if __name__ == "__main__":
    unittest.main()
