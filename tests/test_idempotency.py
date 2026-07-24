"""Idempotency: two create_event calls for the same recurring_rule_id in the
same calendar month must result in exactly one row, and the second call must
raise a clear, handled error -- never a raw DB exception leaking out.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.repository import DuplicateRecurringEventError, EventRepository
from tests.conftest import requires_test_db

pytestmark = requires_test_db


@pytest.fixture
async def seeded(db_session):
    user_id = (await db_session.execute(sa.text(
        "INSERT INTO users (name) VALUES ('Idempotency test') RETURNING id"
    ))).scalar()
    category_id = (await db_session.execute(sa.text(
        "INSERT INTO categories (name, direction) VALUES ('Salary', 'credit') RETURNING id"
    ))).scalar()
    rule_id = (await db_session.execute(sa.text(
        "INSERT INTO recurring_rules "
        "(user_id, label, category_id, expected_amount, direction, day_of_month) "
        "VALUES (:user_id, 'Salary', :category_id, 50000, 'credit', 28) RETURNING id"
    ), {"user_id": user_id, "category_id": category_id})).scalar()
    await db_session.commit()
    return {"user_id": user_id, "category_id": category_id, "rule_id": rule_id}


@pytest.mark.anyio
async def test_second_create_for_same_rule_and_month_raises_handled_error(db_session, seeded):
    repo = EventRepository(db_session)
    expected_at = datetime(2026, 7, 28, tzinfo=timezone.utc)

    await repo.create_event(
        user_id=seeded["user_id"],
        direction="credit",
        category_id=seeded["category_id"],
        recurring_rule_id=seeded["rule_id"],
        source="scheduled",
        status="pending",
        expected_amount=Decimal("50000"),
        expected_at=expected_at,
    )

    with pytest.raises(DuplicateRecurringEventError):
        await repo.create_event(
            user_id=seeded["user_id"],
            direction="credit",
            category_id=seeded["category_id"],
            recurring_rule_id=seeded["rule_id"],
            source="scheduled",
            status="pending",
            expected_amount=Decimal("50000"),
            expected_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        )

    count = (await db_session.execute(sa.text(
        "SELECT count(*) FROM events WHERE recurring_rule_id = :rule_id"
    ), {"rule_id": seeded["rule_id"]})).scalar()
    assert count == 1


@pytest.mark.anyio
async def test_different_month_same_rule_is_allowed(db_session, seeded):
    repo = EventRepository(db_session)

    await repo.create_event(
        user_id=seeded["user_id"],
        direction="credit",
        category_id=seeded["category_id"],
        recurring_rule_id=seeded["rule_id"],
        source="scheduled",
        status="pending",
        expected_amount=Decimal("50000"),
        expected_at=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )
    await repo.create_event(
        user_id=seeded["user_id"],
        direction="credit",
        category_id=seeded["category_id"],
        recurring_rule_id=seeded["rule_id"],
        source="scheduled",
        status="pending",
        expected_amount=Decimal("50000"),
        expected_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )

    count = (await db_session.execute(sa.text(
        "SELECT count(*) FROM events WHERE recurring_rule_id = :rule_id"
    ), {"rule_id": seeded["rule_id"]})).scalar()
    assert count == 2


@pytest.mark.anyio
async def test_manual_events_without_recurring_rule_never_collide(db_session, seeded):
    repo = EventRepository(db_session)

    for _ in range(3):
        await repo.create_event(
            user_id=seeded["user_id"],
            direction="debit",
            category_id=seeded["category_id"],
            recurring_rule_id=None,
            source="manual",
            status="confirmed",
            actual_amount=Decimal("120"),
        )

    count = (await db_session.execute(sa.text(
        "SELECT count(*) FROM events WHERE recurring_rule_id IS NULL"
    ))).scalar()
    assert count == 3
