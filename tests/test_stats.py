"""Fixed fixture events in, known daily/monthly/category totals out.
Only 'confirmed'/'corrected' events count -- 'pending'/'unconfirmed' don't
(see app/stats.py docstring).
"""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa

from app.stats import category_summary, month_summary, today_summary
from tests.conftest import requires_test_db

pytestmark = requires_test_db


@pytest.fixture
async def seeded(db_session):
    user_id = (await db_session.execute(sa.text(
        "INSERT INTO users (name) VALUES ('Stats test') RETURNING id"
    ))).scalar()
    food_id = (await db_session.execute(sa.text(
        "INSERT INTO categories (name, direction) VALUES ('Food', 'debit') RETURNING id"
    ))).scalar()
    salary_id = (await db_session.execute(sa.text(
        "INSERT INTO categories (name, direction) VALUES ('Salary', 'credit') RETURNING id"
    ))).scalar()

    async def insert_event(category_id, direction, status, actual_amount, event_at, notes=None):
        await db_session.execute(sa.text(
            "INSERT INTO events "
            "(user_id, direction, category_id, status, source, actual_amount, event_at, notes) "
            "VALUES (:user_id, :direction, :category_id, :status, 'manual', :amount, :event_at, :notes)"
        ), {
            "user_id": user_id, "direction": direction, "category_id": category_id,
            "status": status, "amount": actual_amount, "event_at": event_at, "notes": notes,
        })

    today = datetime(2026, 7, 24, 9, 0, tzinfo=timezone.utc)
    yesterday = datetime(2026, 7, 23, 9, 0, tzinfo=timezone.utc)
    last_month = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)

    # counts toward today_summary + July month_summary
    await insert_event(food_id, "debit", "confirmed", Decimal("120"), today, "lunch")
    await insert_event(salary_id, "credit", "confirmed", Decimal("50000"), today)
    # counts toward July month_summary only (not today)
    await insert_event(food_id, "debit", "confirmed", Decimal("300"), yesterday)
    # pending -- must NOT count anywhere
    await insert_event(food_id, "debit", "pending", Decimal("999"), today)
    # last month -- counts toward category_summary trend, not July month_summary
    await insert_event(food_id, "debit", "confirmed", Decimal("200"), last_month)

    await db_session.commit()
    return {"user_id": user_id}


@pytest.mark.anyio
async def test_today_summary_totals_and_excludes_pending(db_session, seeded):
    result = await today_summary(db_session, seeded["user_id"], today=date(2026, 7, 24))

    assert result["debit_total"] == Decimal("120")
    assert result["credit_total"] == Decimal("50000")
    assert len(result["events"]) == 2


@pytest.mark.anyio
async def test_month_summary_totals_by_category(db_session, seeded):
    result = await month_summary(db_session, seeded["user_id"], month=date(2026, 7, 1))

    assert result["month"] == "2026-07"
    assert result["by_category"] == {"Food": Decimal("420"), "Salary": Decimal("50000")}
    assert result["debit_total"] == Decimal("420")
    assert result["credit_total"] == Decimal("50000")


@pytest.mark.anyio
async def test_category_summary_trend_across_months(db_session, seeded):
    result = await category_summary(db_session, seeded["user_id"], "Food")

    assert result == [
        {"month": "2026-06", "total": Decimal("200")},
        {"month": "2026-07", "total": Decimal("420")},
    ]
