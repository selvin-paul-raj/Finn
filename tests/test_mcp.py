"""MCP server tests: unauthenticated calls rejected before tool logic runs
(asserted first); each of the 5 tools returns correct data against fixtures
once authenticated.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import sqlalchemy as sa
from starlette.testclient import TestClient

import app.mcp_server as mcp_server
from tests.conftest import requires_test_db

pytestmark = requires_test_db

WRONG_HEADERS = {"Authorization": "Bearer wrong-token"}


def test_unauthenticated_request_rejected_before_any_tool_logic():
    client = TestClient(mcp_server.mcp_asgi_app, raise_server_exceptions=False)
    response = client.post("/", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})
    assert response.status_code == 401


def test_wrong_token_rejected_before_any_tool_logic():
    client = TestClient(mcp_server.mcp_asgi_app, raise_server_exceptions=False)
    response = client.post(
        "/", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1}, headers=WRONG_HEADERS
    )
    assert response.status_code == 401


@pytest.fixture
async def seeded(test_session_factory, monkeypatch):
    monkeypatch.setattr(mcp_server, "async_session_factory", test_session_factory)

    async with test_session_factory() as session:
        user_id = (await session.execute(sa.text(
            "INSERT INTO users (name) VALUES ('MCP test') RETURNING id"
        ))).scalar()
        food_id = (await session.execute(sa.text(
            "INSERT INTO categories (name, direction) VALUES ('Food', 'debit') RETURNING id"
        ))).scalar()
        today = datetime.now(timezone.utc)
        await session.execute(sa.text(
            "INSERT INTO events "
            "(user_id, direction, category_id, status, source, actual_amount, event_at) "
            "VALUES (:user_id, 'debit', :category_id, 'confirmed', 'manual', 120, :event_at)"
        ), {"user_id": user_id, "category_id": food_id, "event_at": today})
        pending_id = (await session.execute(sa.text(
            "INSERT INTO events "
            "(user_id, direction, category_id, status, source, expected_amount, expected_at) "
            "VALUES (:user_id, 'debit', :category_id, 'pending', 'scheduled', 500, :expected_at) "
            "RETURNING id"
        ), {"user_id": user_id, "category_id": food_id, "expected_at": today})).scalar()
        await session.commit()

    return {"user_id": user_id, "food_id": food_id, "pending_id": pending_id}


@pytest.mark.anyio
async def test_today_summary_tool_returns_correct_data(seeded):
    result = await mcp_server.mcp.call_tool("today_summary", {})
    payload = _unwrap(result)
    assert Decimal(payload["debit_total"]) == Decimal("120")


@pytest.mark.anyio
async def test_month_summary_tool_returns_correct_data(seeded):
    result = await mcp_server.mcp.call_tool("month_summary", {})
    payload = _unwrap(result)
    assert Decimal(payload["by_category"]["Food"]) == Decimal("120")


@pytest.mark.anyio
async def test_category_summary_tool_returns_correct_data(seeded):
    result = await mcp_server.mcp.call_tool("category_summary", {"category": "Food"})
    payload = _unwrap(result)
    assert Decimal(payload[0]["total"]) == Decimal("120")


@pytest.mark.anyio
async def test_pending_events_tool_returns_correct_data(seeded):
    result = await mcp_server.mcp.call_tool("pending_events", {})
    payload = _unwrap(result)
    assert len(payload) == 1
    assert payload[0]["id"] == str(seeded["pending_id"])
    assert Decimal(payload[0]["expected_amount"]) == Decimal("500")


@pytest.mark.anyio
async def test_log_event_tool_parses_and_writes_event(seeded, monkeypatch):
    async def fake_call_gemini(self, text):
        return {"direction": "debit", "amount": "45", "category": "Transport", "confidence": 0.92}

    monkeypatch.setattr(mcp_server.GeminiEventParser, "_call_gemini", fake_call_gemini)

    result = await mcp_server.mcp.call_tool("log_event", {"text": "cab 45"})
    payload = _unwrap(result)

    assert Decimal(payload["amount"]) == Decimal("45")
    assert payload["category"] == "Transport"
    assert payload["status"] == "confirmed"


def _unwrap(result):
    """FastMCP's call_tool(name, args) return shape depends on whether an
    output schema was inferred from the tool's return-type annotation:
    - `-> list[...]`: a (content_blocks, structured_dict) tuple, where
      structured_dict is {"result": [...]} (top-level lists get wrapped).
    - `-> dict`: no output schema inferred (too generic to build one from),
      so it's a bare list of one TextContent block with the JSON dict as text.
    """
    if isinstance(result, tuple):
        _content, structured = result
        if structured is not None:
            return structured.get("result", structured)
        result = _content
    return json.loads(result[0].text)
