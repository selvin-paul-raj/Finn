from contextlib import asynccontextmanager
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request

from app import telegram
from app.config import FEATURES, TRIGGER_SECRET
from app.db import async_session_factory
from app.models import RecurringRule
from app.repository import DuplicateRecurringEventError, EventRepository, get_default_user_id
from app.scheduler_logic import is_due_today


def verify_bearer_token(authorization_header: str | None, expected: str) -> None:
    """Shared bearer-token check for /trigger, /mcp, /webhook (see DECISIONS.md)."""
    if authorization_header != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


# Imported here (after verify_bearer_token, before `app = FastAPI(...)`):
# app.mcp_server imports verify_bearer_token from this module at its own
# import time (avoids a circular-import failure), and FastMCP's session
# manager needs its lifespan wired into FastAPI's own lifespan below --
# a plain app.mount() does NOT propagate a mounted sub-app's lifespan.
from app.mcp_server import mcp, mcp_asgi_app  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Finn", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    """Absorbs Render's cold start before /trigger -- see daily-checkin.yml."""
    return {"status": "ok"}


@app.post("/trigger")
async def trigger(request: Request) -> dict:
    verify_bearer_token(request.headers.get("authorization"), TRIGGER_SECRET)

    if not FEATURES["scheduler_enabled"]:
        return {"ok": True, "skipped": "scheduler disabled"}

    today = datetime.now(timezone.utc).date()
    created_ids: list[str] = []
    chat_id = None

    async with async_session_factory() as session:
        user_id = await get_default_user_id(session)
        result = await session.execute(
            sa.select(RecurringRule).where(
                RecurringRule.user_id == user_id, RecurringRule.active.is_(True)
            )
        )
        repo = EventRepository(session)
        for rule in result.scalars().all():
            if not is_due_today(rule, today):
                continue
            try:
                event = await repo.create_event(
                    user_id=user_id,
                    direction=rule.direction,
                    category_id=rule.category_id,
                    recurring_rule_id=rule.id,
                    source="scheduled",
                    status="pending",
                    expected_amount=rule.expected_amount,
                    expected_at=datetime.now(timezone.utc),
                )
                created_ids.append(str(event.id))
            except DuplicateRecurringEventError:
                continue  # already generated this month -- /trigger is safe to call more than once

        if created_ids and FEATURES["telegram_enabled"]:
            chat_id = (await session.execute(
                sa.text("SELECT telegram_chat_id FROM users WHERE id = :user_id"),
                {"user_id": user_id},
            )).scalar()

    if chat_id is not None:
        rule_word = "reminder" if len(created_ids) == 1 else "reminders"
        await telegram.send_message(
            chat_id, f"{len(created_ids)} recurring {rule_word} due today -- reply to confirm."
        )

    return {"ok": True, "created": created_ids}


@app.post("/webhook")
async def webhook(request: Request) -> dict:
    payload = await request.json()
    secret_header = request.headers.get("x-telegram-bot-api-secret-token")
    return await telegram.handle_webhook(payload, secret_header)


# FastMCP's streamable_http_app() already serves at "/mcp" internally, so
# mount at root -- mounting at "/mcp" here would double up to "/mcp/mcp".
app.mount("/", mcp_asgi_app)
