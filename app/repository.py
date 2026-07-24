"""EventRepository -- all SQL for events lives here (see DECISIONS.md)."""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Event, User


async def get_default_user_id(session: AsyncSession) -> uuid.UUID:
    """Single-user system for v1 (README.md) -- operate on the one users row."""
    result = await session.execute(select(User.id).limit(1))
    user_id = result.scalar()
    if user_id is None:
        raise RuntimeError("No user exists yet -- seed one before using this")
    return user_id


async def get_or_create_category_id(session: AsyncSession, name: str) -> uuid.UUID:
    """Get-or-create by name. New categories default direction='either' since
    the same label (e.g. "Other") may end up used for both credit and debit
    events -- the event's own `direction` column is authoritative either way."""
    result = await session.execute(select(Category.id).where(Category.name == name))
    category_id = result.scalar()
    if category_id is not None:
        return category_id
    category = Category(name=name, direction="either")
    session.add(category)
    await session.flush()
    return category.id


class DuplicateRecurringEventError(Exception):
    """Raised instead of a raw IntegrityError when a second event for the
    same recurring_rule_id + calendar month is attempted (ux_recurring_cycle)."""

    def __init__(self, recurring_rule_id):
        self.recurring_rule_id = recurring_rule_id
        super().__init__(
            f"An event for recurring_rule_id={recurring_rule_id} already "
            "exists for this month"
        )


class EventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_event(self, **fields) -> Event:
        event = Event(**fields)
        self.session.add(event)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            if "ux_recurring_cycle" in str(exc.orig):
                raise DuplicateRecurringEventError(fields.get("recurring_rule_id")) from exc
            raise
        await self.session.refresh(event)
        return event

    async def update_event(self, event_id, **fields) -> Event:
        event = await self.session.get(Event, event_id)
        if event is None:
            raise ValueError(f"No event with id={event_id}")
        for key, value in fields.items():
            setattr(event, key, value)
        event.version += 1
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def get_pending_events(self, user_id) -> list[Event]:
        result = await self.session.execute(
            select(Event)
            .where(Event.user_id == user_id, Event.status == "pending")
            .order_by(Event.expected_at)
        )
        return list(result.scalars().all())
