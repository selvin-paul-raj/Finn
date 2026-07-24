"""Telegram webhook handling + outbound message sending via httpx.

Telegram doesn't sign webhook payloads the way e.g. Stripe does -- its
equivalent is the `X-Telegram-Bot-Api-Secret-Token` header, set once when
registering the webhook (`setWebhook(secret_token=...)`) and echoed back on
every real call. Rejected before any payload parsing, same shared-secret
pattern as /trigger and /mcp (see DECISIONS.md).
"""

from datetime import datetime, timezone

import httpx
import sqlalchemy as sa
from fastapi import HTTPException
from pydantic import ValidationError


from app.config import TELEGRAM_BOT_TOKEN, TRIGGER_SECRET
from app.db import async_session_factory
from app.parser import NvidiaEventParser, ParsedEvent
from app.repository import EventRepository, get_default_user_id, get_or_create_category_id

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


def verify_telegram_secret(secret_header: str | None) -> None:
    if secret_header != TRIGGER_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing Telegram secret token")


def _extract_message(payload: dict) -> tuple[int, str] | None:
    """Pull (chat_id, text) out of a Telegram Update payload, or None if this
    update isn't a plain text message (photo, edited message, etc.)."""
    message = payload.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    text = message.get("text")
    if not isinstance(chat, dict) or not isinstance(text, str) or not text:
        return None
    chat_id = chat.get("id")
    if not isinstance(chat_id, int):
        return None
    return chat_id, text


def _confirmation_text(parsed: ParsedEvent, status: str) -> str:
    verb = "Received" if parsed.direction == "credit" else "Logged"
    text = f"{verb}: {parsed.amount} - {parsed.category}"
    if status == "unconfirmed":
        text += " (low confidence -- reply to correct if this is wrong)"
    return text


async def handle_webhook(payload: dict, secret_header: str | None) -> dict:
    """Invalid/unsigned payloads are rejected before any parsing happens."""
    verify_telegram_secret(secret_header)

    extracted = _extract_message(payload)
    if extracted is None:
        return {"ok": True, "skipped": "not a text message"}
    chat_id, text = extracted

    if text.startswith("/"):
        # Bind the chat_id for reminders on first contact
        async with async_session_factory() as session:
            user_id = await get_default_user_id(session)
            await session.execute(
                sa.text(
                    "UPDATE users SET telegram_chat_id = :chat_id "
                    "WHERE id = :user_id AND telegram_chat_id IS NULL"
                ),
                {"chat_id": chat_id, "user_id": user_id},
            )
            await session.commit()

        greeting = (
            "Welcome to Finn! 🚀\n\n"
            "I am your personal finance tracker bot. You can log expenses or income by messaging me in plain text.\n"
            "Examples:\n"
            "- 'lunch 120'\n"
            "- 'friend gave 500 for dinner'\n"
            "- 'salary 50000'\n\n"
            "Send me a transaction to get started!"
        )
        await send_message(chat_id, greeting)
        return {"ok": True, "command": text}

    try:
        parsed = await NvidiaEventParser().parse(text)
    except ValidationError:
        await send_message(
            chat_id,
            "I couldn't parse that transaction. Please try again (e.g., 'lunch 120' or 'salary 5000')."
        )
        return {"ok": True, "error": "parse_validation_error"}

    async with async_session_factory() as session:
        user_id = await get_default_user_id(session)
        # Bind only on first contact -- never overwrite an already-linked
        # chat_id, so a later message (even one authenticated by the shared
        # webhook secret) can't silently hijack where reminders get sent.
        await session.execute(
            sa.text(
                "UPDATE users SET telegram_chat_id = :chat_id "
                "WHERE id = :user_id AND telegram_chat_id IS NULL"
            ),
            {"chat_id": chat_id, "user_id": user_id},
        )
        category_id = await get_or_create_category_id(session, parsed.category)
        status = "confirmed" if parsed.confidence >= 0.8 else "unconfirmed"
        event = await EventRepository(session).create_event(
            user_id=user_id,
            direction=parsed.direction,
            category_id=category_id,
            source="manual",
            status=status,
            actual_amount=parsed.amount,
            event_at=datetime.now(timezone.utc),
            raw_text=text,
            notes=parsed.notes,
            confidence=parsed.confidence,
        )

    await send_message(chat_id, _confirmation_text(parsed, status))
    return {"ok": True, "event_id": str(event.id)}


async def send_message(chat_id: int, text: str) -> None:
    url = _TELEGRAM_API.format(token=TELEGRAM_BOT_TOKEN, method="sendMessage")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json={"chat_id": chat_id, "text": text})
        response.raise_for_status()
