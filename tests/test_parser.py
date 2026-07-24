"""Parser tests: fixed input strings -> expected ParsedEvent output.

NVIDIA is mocked (`NvidiaEventParser._call_nvidia`) — no live API calls here.
"""

from decimal import Decimal

import pytest

from app.parser import NvidiaEventParser
from app.schemas import ParsedEvent


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_parse_lunch_expense(monkeypatch):
    async def fake_call_nvidia(self, text):
        return {
            "direction": "debit",
            "amount": "120",
            "category": "Food",
            "confidence": 0.95,
        }

    monkeypatch.setattr(NvidiaEventParser, "_call_nvidia", fake_call_nvidia)

    parser = NvidiaEventParser()
    result = await parser.parse("lunch 120")

    assert result == ParsedEvent(
        direction="debit",
        amount=Decimal("120"),
        category="Food",
        confidence=0.95,
    )


@pytest.mark.anyio
async def test_parse_friend_gave_money_no_reason(monkeypatch):
    async def fake_call_nvidia(self, text):
        return {
            "direction": "credit",
            "amount": "500",
            "category": "Other",
            "confidence": 0.8,
            "notes": "no reason given",
        }

    monkeypatch.setattr(NvidiaEventParser, "_call_nvidia", fake_call_nvidia)

    parser = NvidiaEventParser()
    result = await parser.parse("friend gave 500 no reason")

    assert result == ParsedEvent(
        direction="credit",
        amount=Decimal("500"),
        category="Other",
        confidence=0.8,
        notes="no reason given",
    )


@pytest.mark.anyio
async def test_parse_emi_paid(monkeypatch):
    async def fake_call_nvidia(self, text):
        return {
            "direction": "debit",
            "amount": "1500",
            "category": "EMI",
            "confidence": 0.9,
        }

    monkeypatch.setattr(NvidiaEventParser, "_call_nvidia", fake_call_nvidia)

    parser = NvidiaEventParser()
    result = await parser.parse("EMI paid")

    assert result == ParsedEvent(
        direction="debit",
        amount=Decimal("1500"),
        category="EMI",
        confidence=0.9,
    )


@pytest.mark.anyio
async def test_parse_low_confidence_is_surfaced_not_dropped(monkeypatch):
    """Confidence-threshold decision logic is out of scope for this task —
    only assert the raw low confidence value survives into ParsedEvent."""

    async def fake_call_nvidia(self, text):
        return {
            "direction": "debit",
            "amount": "50",
            "category": "Misc",
            "confidence": 0.3,
        }

    monkeypatch.setattr(NvidiaEventParser, "_call_nvidia", fake_call_nvidia)

    parser = NvidiaEventParser()
    result = await parser.parse("something unclear")

    assert result.confidence == 0.3
