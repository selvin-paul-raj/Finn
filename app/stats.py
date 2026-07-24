"""today/month/category summaries -- plain SQL via EventRepository's session,
no precompute needed at this scale (TECHNICAL_REPORT.md #4).

Only 'confirmed'/'corrected' events count toward totals -- 'pending' and
'unconfirmed' amounts aren't settled numbers yet (see SCHEMA_AND_FLOW_DESIGN.md
section 4's state machine), so including them would silently overstate spend
before a user ever confirmed it.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Event

SETTLED_STATUSES = ("confirmed", "corrected")
_SETTLED_AMOUNT = sa.func.coalesce(Event.actual_amount, Event.expected_amount)


async def today_summary(session: AsyncSession, user_id, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    result = await session.execute(
        sa.select(Event.direction, Category.name, _SETTLED_AMOUNT, Event.notes)
        .join(Category, Category.id == Event.category_id)
        .where(
            Event.user_id == user_id,
            Event.status.in_(SETTLED_STATUSES),
            sa.func.date(Event.event_at) == today,
        )
    )
    credit_total = Decimal("0")
    debit_total = Decimal("0")
    events = []
    for direction, category, amount, notes in result.all():
        amount = amount or Decimal("0")
        if direction == "credit":
            credit_total += amount
        else:
            debit_total += amount
        events.append({"direction": direction, "category": category, "amount": amount, "notes": notes})
    return {"date": today.isoformat(), "credit_total": credit_total, "debit_total": debit_total, "events": events}


async def month_summary(session: AsyncSession, user_id, month: date | None = None) -> dict:
    month_start = (month or datetime.now(timezone.utc).date()).replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)

    result = await session.execute(
        sa.select(Category.name, _SETTLED_AMOUNT, Event.direction)
        .join(Category, Category.id == Event.category_id)
        .where(
            Event.user_id == user_id,
            Event.status.in_(SETTLED_STATUSES),
            Event.event_at >= month_start,
            Event.event_at < next_month,
        )
    )
    by_category: dict[str, Decimal] = {}
    credit_total = Decimal("0")
    debit_total = Decimal("0")
    for category, amount, direction in result.all():
        amount = amount or Decimal("0")
        by_category[category] = by_category.get(category, Decimal("0")) + amount
        if direction == "credit":
            credit_total += amount
        else:
            debit_total += amount

    return {
        "month": month_start.strftime("%Y-%m"),
        "by_category": by_category,
        "credit_total": credit_total,
        "debit_total": debit_total,
    }


async def category_summary(session: AsyncSession, user_id, category: str) -> list[dict]:
    month_bucket = sa.func.date_trunc("month", Event.event_at)
    result = await session.execute(
        sa.select(month_bucket, sa.func.sum(_SETTLED_AMOUNT))
        .join(Category, Category.id == Event.category_id)
        .where(
            Event.user_id == user_id,
            Category.name == category,
            Event.status.in_(SETTLED_STATUSES),
        )
        .group_by(month_bucket)
        .order_by(month_bucket)
    )
    return [
        {"month": month.strftime("%Y-%m"), "total": total or Decimal("0")}
        for month, total in result.all()
    ]
