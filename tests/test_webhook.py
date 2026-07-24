"""Webhook tests: invalid/unsigned payload rejected before parsing; a valid
Telegram message payload results in the parser being called and an event
being written via the repository.
"""

from decimal import Decimal

import pytest
import sqlalchemy as sa

import app.telegram as telegram
from tests.conftest import requires_test_db

pytestmark = requires_test_db

VALID_SECRET = "test-telegram-secret"


@pytest.fixture(autouse=True)
def patched_secret(monkeypatch):
    monkeypatch.setattr(telegram, "TRIGGER_SECRET", VALID_SECRET)


@pytest.fixture(autouse=True)
def no_real_telegram_calls(monkeypatch):
    """Never let a test actually hit the Telegram API."""
    sent = []

    async def fake_send_message(chat_id, text):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram, "send_message", fake_send_message)
    return sent


@pytest.fixture
async def seeded(test_session_factory, monkeypatch):
    monkeypatch.setattr(telegram, "async_session_factory", test_session_factory)
    async with test_session_factory() as session:
        user_id = (await session.execute(sa.text(
            "INSERT INTO users (name) VALUES ('Webhook test') RETURNING id"
        ))).scalar()
        await session.commit()
    return {"user_id": user_id}


TELEGRAM_UPDATE = {
    "update_id": 1,
    "message": {
        "message_id": 1,
        "chat": {"id": 555, "type": "private"},
        "text": "lunch 120",
    },
}


@pytest.mark.anyio
async def test_missing_secret_header_rejected_before_parsing(seeded, monkeypatch):
    called = []

    async def fake_parse(self, text):
        called.append(text)
        raise AssertionError("parser must not be called for an unauthenticated request")

    monkeypatch.setattr(telegram.GeminiEventParser, "parse", fake_parse)

    with pytest.raises(Exception) as exc_info:
        await telegram.handle_webhook(TELEGRAM_UPDATE, None)
    assert getattr(exc_info.value, "status_code", None) == 401
    assert called == []


@pytest.mark.anyio
async def test_wrong_secret_header_rejected_before_parsing(seeded, monkeypatch):
    called = []

    async def fake_parse(self, text):
        called.append(text)
        raise AssertionError("parser must not be called for an unauthenticated request")

    monkeypatch.setattr(telegram.GeminiEventParser, "parse", fake_parse)

    with pytest.raises(Exception) as exc_info:
        await telegram.handle_webhook(TELEGRAM_UPDATE, "wrong-secret")
    assert getattr(exc_info.value, "status_code", None) == 401
    assert called == []


@pytest.mark.anyio
async def test_valid_message_calls_parser_and_writes_event(
    seeded, no_real_telegram_calls, monkeypatch
):
    async def fake_call_gemini(self, text):
        return {"direction": "debit", "amount": "120", "category": "Food", "confidence": 0.95}

    monkeypatch.setattr(telegram.GeminiEventParser, "_call_gemini", fake_call_gemini)

    result = await telegram.handle_webhook(TELEGRAM_UPDATE, VALID_SECRET)

    assert result["ok"] is True
    assert "event_id" in result
    assert len(no_real_telegram_calls) == 1
    assert no_real_telegram_calls[0][0] == 555


@pytest.mark.anyio
async def test_valid_message_writes_row_matching_parsed_event(
    seeded, no_real_telegram_calls, test_session_factory, monkeypatch
):
    monkeypatch.setattr(telegram, "async_session_factory", test_session_factory)

    async def fake_call_gemini(self, text):
        return {"direction": "debit", "amount": "120", "category": "Food", "confidence": 0.95}

    monkeypatch.setattr(telegram.GeminiEventParser, "_call_gemini", fake_call_gemini)

    await telegram.handle_webhook(TELEGRAM_UPDATE, VALID_SECRET)

    async with test_session_factory() as session:
        row = (await session.execute(sa.text(
            "SELECT actual_amount, direction, status, raw_text FROM events "
            "WHERE user_id = :user_id"
        ), {"user_id": seeded["user_id"]})).one()

    assert row.actual_amount == Decimal("120.00")
    assert row.direction == "debit"
    assert row.status == "confirmed"
    assert row.raw_text == "lunch 120"


@pytest.mark.anyio
async def test_non_text_update_is_skipped_without_error(seeded):
    result = await telegram.handle_webhook({"update_id": 2, "edited_message": {}}, VALID_SECRET)
    assert result == {"ok": True, "skipped": "not a text message"}
