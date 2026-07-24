"""The 5 MCP tools for v1 (SCHEMA_AND_FLOW_DESIGN.md section 5), mounted at
/mcp, gated by the same bearer-token dependency as /trigger and /webhook.

Single-user system (README.md): tools operate on the one row in `users`.
"""

from datetime import date, datetime, timezone

from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import MCP_API_KEY
from app.db import async_session_factory
from app.main import verify_bearer_token
from app.parser import NvidiaEventParser
from app.repository import EventRepository, get_default_user_id, get_or_create_category_id
from app.stats import category_summary as _category_summary_query
from app.stats import month_summary as _month_summary_query
from app.stats import today_summary as _today_summary_query

mcp = FastMCP("finn")


def _decimalize(value) -> str | None:
    return str(value) if value is not None else None


def _serialize_summary(result: dict) -> dict:
    serialized = dict(result)
    if "by_category" in serialized:
        serialized["by_category"] = {k: _decimalize(v) for k, v in serialized["by_category"].items()}
    for key in ("credit_total", "debit_total"):
        if key in serialized:
            serialized[key] = _decimalize(serialized[key])
    if "events" in serialized:
        serialized["events"] = [
            {**event, "amount": _decimalize(event["amount"])} for event in serialized["events"]
        ]
    return serialized


@mcp.tool()
async def log_event(text: str) -> dict:
    """Parse free-text finance message and write one event."""
    parser = NvidiaEventParser()
    parsed = await parser.parse(text)

    async with async_session_factory() as session:
        user_id = await get_default_user_id(session)
        category_id = await get_or_create_category_id(session, parsed.category)
        repo = EventRepository(session)
        status = "confirmed" if parsed.confidence >= 0.8 else "unconfirmed"
        event = await repo.create_event(
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
        return {
            "id": str(event.id),
            "direction": event.direction,
            "amount": _decimalize(event.actual_amount),
            "category": parsed.category,
            "status": event.status,
            "confidence": float(event.confidence) if event.confidence is not None else None,
        }


@mcp.tool()
async def today_summary() -> dict:
    """Today's confirmed events, grouped by direction."""
    async with async_session_factory() as session:
        user_id = await get_default_user_id(session)
        result = await _today_summary_query(session, user_id)
    return _serialize_summary(result)


@mcp.tool()
async def month_summary(month: str | None = None) -> dict:
    """Totals by category for the given (YYYY-MM) or current month."""
    month_date: date | None = None
    if month:
        try:
            month_date = datetime.strptime(month, "%Y-%m").date().replace(day=1)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="month must be 'YYYY-MM'") from exc

    async with async_session_factory() as session:
        user_id = await get_default_user_id(session)
        result = await _month_summary_query(session, user_id, month_date)
    return _serialize_summary(result)


@mcp.tool()
async def category_summary(category: str) -> list[dict]:
    """Spend trend for one category over time."""
    async with async_session_factory() as session:
        user_id = await get_default_user_id(session)
        result = await _category_summary_query(session, user_id, category)
    return [{"month": row["month"], "total": _decimalize(row["total"])} for row in result]


@mcp.tool()
async def pending_events() -> list[dict]:
    """Anything awaiting confirmation right now."""
    async with async_session_factory() as session:
        user_id = await get_default_user_id(session)
        events = await EventRepository(session).get_pending_events(user_id)
    return [
        {
            "id": str(event.id),
            "direction": event.direction,
            "expected_amount": _decimalize(event.expected_amount),
            "expected_at": event.expected_at.isoformat() if event.expected_at else None,
            "status": event.status,
        }
        for event in events
    ]


class _BearerAuthMiddleware:
    """Wraps the MCP ASGI app: identity -> authorization -> tool -> database,
    per SCHEMA_AND_FLOW_DESIGN.md section 5's security model. Rejects before
    any tool logic runs, not inside it."""

    def __init__(self, inner: ASGIApp, expected_token: str):
        self.inner = inner
        self.expected_token = expected_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode() or None
        try:
            verify_bearer_token(auth_header, self.expected_token)
        except HTTPException as exc:
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
            await response(scope, receive, send)
            return

        await self.inner(scope, receive, send)


mcp_asgi_app = _BearerAuthMiddleware(mcp.streamable_http_app(), MCP_API_KEY)
