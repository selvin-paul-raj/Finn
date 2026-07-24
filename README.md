# Personal Finance Tracker

A scheduled, user-seeded, chat-first personal finance tracker. You log
expenses by texting Telegram in plain English, recurring items (salary,
EMI, SIP) get confirmed via scheduled pings, and any MCP-capable AI client
(Claude, ChatGPT) can query your own data as a "second opinion" — all on
free-tier infrastructure.

> **Full design detail lives in two companion docs, read those before
> writing code:**
> - [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md) — stack,
>   packages, folder structure, testing strategy, deployment steps
> - [`docs/SCHEMA_AND_FLOW_DESIGN.md`](docs/SCHEMA_AND_FLOW_DESIGN.md) —
>   DDL, ERD, state machine, conversation flow, MCP tools, and future-scoped
>   extension notes
>
> **Status:** v1 spec frozen for build. No design changes until 30 days of
> real usage data justify them.

---

## Core principle

Everything is an `event`. One table (`events`) does the work five separate
tables would otherwise do — logged expenses, recurring salary/EMI/SIP
confirmations, and corrections all live there, distinguished by
`recurring_rule_id`, `status`, and `source`, not by separate schemas.

## What "done" looks like for v1

1. Log expenses by chatting naturally with the Telegram bot
2. Get recurring reminders for salary/EMI/SIP that trigger on the right day
3. See daily/weekly/monthly/category summaries
4. Ask Claude or ChatGPT (via MCP) questions about your own data, securely

---

## Architecture

```
   Claude / ChatGPT (dev mode) / any MCP client
                    |
              MCP server (auth-scoped per user, /mcp route)
                    |
              FastAPI backend on Render  <-- all business logic, validation
                 /      \
        Gemini API      Neon (serverless Postgres)
    (parse text only,   (source of truth,
     no DB access)       stats via plain SQL)

   GitHub Actions (cron, 2x/day) --> /healthz --> /trigger
   Telegram webhook               --> /webhook   (real-time chat)
   GitHub Actions (nightly)       --> pg_dump --> GitHub artifact backup
```

| Layer | Choice | Free tier |
|---|---|---|
| Chat interface | Telegram Bot API | Unlimited (personal use) |
| Backend | FastAPI (Python 3.12) on Render | 750 instance-hrs/mo, ~30-60s cold start |
| Database | Neon (serverless Postgres) | 0.5 GB storage, 100 compute-hrs/mo |
| Scheduler | GitHub Actions `cron:` | 2,000 Action-minutes/mo |
| AI parsing | Gemini API | Free-tier RPM/RPD caps |
| MCP server | Same FastAPI app, `/mcp` route | Same as backend |

Full rationale, including *why not* Render Postgres and *why not* Render
Cron, is in `docs/TECHNICAL_REPORT.md` §1.

---

## Repo structure

```
finance-tracker/
├── app/
│   ├── main.py              # FastAPI app: routes only, no business logic
│   ├── config.py            # env vars + FEATURES flag dict
│   ├── db.py                 # SQLAlchemy engine/session, Neon connection
│   ├── models.py             # SQLAlchemy models, mirrors the DDL exactly
│   ├── schemas.py             # Pydantic shapes, incl. ParsedEvent
│   ├── parser.py              # EventParser protocol + GeminiEventParser
│   ├── telegram.py            # webhook handling, message sending
│   ├── scheduler_logic.py     # "what's due today", called by /trigger
│   ├── stats.py                # daily/monthly/category summaries
│   ├── repository.py           # EventRepository -- all SQL lives here
│   ├── mcp_server.py            # the 5 MCP tools, mounted at /mcp
│   └── logging_config.py        # structured JSON logging
├── alembic/                      # migrations, one revision per schema change
├── tests/                         # pytest + pytest-asyncio, see below
├── .github/workflows/
│   ├── daily-checkin.yml           # 2x/day scheduler
│   └── nightly-backup.yml           # pg_dump -> GitHub artifact
├── docs/
│   ├── TECHNICAL_REPORT.md
│   └── SCHEMA_AND_FLOW_DESIGN.md
├── requirements.txt
├── .env.example
└── README.md                        # this file
```

One service, one repo, flat imports. No `apps/`, no `packages/`, no
`docker-compose.yml`. Don't restructure unless this genuinely outgrows a
single deployable unit.

---

## Environment variables

Documented in `.env.example`, never committed as real secrets:

```
DATABASE_URL=            # Neon connection string
GEMINI_API_KEY=
TELEGRAM_BOT_TOKEN=
TRIGGER_SECRET=          # bearer token GitHub Actions uses to call /trigger
MCP_API_KEY=             # scopes /mcp to you specifically
```

Locally: put these in `.env` (git-ignored). In production: Render env vars
+ GitHub Actions repo secrets — same names, never the repo itself.

---

## Quick start (local)

```bash
git clone <your-repo-url> finance-tracker && cd finance-tracker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in DATABASE_URL, GEMINI_API_KEY, TELEGRAM_BOT_TOKEN

alembic init alembic                             # first time only
alembic revision --autogenerate -m "initial schema"
alembic upgrade head

uvicorn app.main:app --reload
```

Run tests:
```bash
pytest
```
Test priority order (write before the feature, not after) — idempotency
first, then parser, scheduler, stats, then MCP/webhook auth. Full rationale
in `docs/TECHNICAL_REPORT.md` §5.

---

## Deploy (free tier, step by step)

1. **Provision first, before app code:**
   Neon project → run DDL from `docs/SCHEMA_AND_FLOW_DESIGN.md` §2 →
   Telegram bot via @BotFather → Gemini API key from Google AI Studio →
   private GitHub repo with all secrets under
   Settings → Secrets and variables → Actions.

2. **Backend on Render:** connect the repo as a free web service.
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
   - Add the same secrets as Render environment variables.
   - Register the Telegram webhook once:
     ```
     curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-render-url>/webhook"
     ```

3. **Scheduler:** `.github/workflows/daily-checkin.yml` fires at ~8am and
   ~8pm IST, hits `/healthz` then `/trigger` (two-request pattern absorbs
   Render's cold start).

4. **MCP server:** same FastAPI app, `/mcp` route, gated by `MCP_API_KEY`.
   Point Claude's (and ChatGPT's Developer Mode, if available) custom
   connector at `https://<your-render-url>/mcp`.

5. **Verify, for real, over real days** before calling this "deployed":
   - Telegram message arrives on schedule, twice a day
   - A recurring salary/EMI ping fires inside its window
   - `month_summary()` returns correct numbers via Claude or ChatGPT
   - A cold start doesn't silently drop a ping (trigger manually after
     20+ min of Render inactivity and confirm the message still arrives)

Full deployment detail, including the nightly backup workflow and
free-tier failure-mode table, is in `docs/TECHNICAL_REPORT.md` §8–10.

---

## MCP tools (exactly five, v1)

```
log_event(text)              -> parses + writes one event
today_summary()               -> today's confirmed events, grouped by direction
month_summary(month?)         -> totals by category for the given/current month
category_summary(category)    -> spend trend for one category over time
pending_events()              -> anything awaiting confirmation right now
```

Security model (build before tool #2, not after): Gemini only ever sees raw
message text, never balances or history; every MCP call goes identity →
authorization → tool → database; the backend validates every field Gemini
returns before writing it — model output is untrusted input, same as any
HTTP request body.

---

## What's explicitly out of scope for v1

Do not build until 30 days of real usage says otherwise: `people`/`loans`
tables, per-user categories, knowledge graph/embeddings/vector search,
SMS/email parsing or Account Aggregator integration, receipt OCR,
forecasting/cash-flow prediction, investment tracking, a swappable-LLM
abstraction, any MCP tool beyond the five above, and any use of
`metadata JSONB` you'd ever want to query on.

Design notes on *how* each of these would extend the schema later, without
requiring a rewrite, are in `docs/SCHEMA_AND_FLOW_DESIGN.md` §8 — read that
before deciding any of them is worth building early.

---

## 30-day success metrics

| Metric | Target |
|---|---|
| Daily check-in completion rate | > 80% |
| Average follow-up questions per event | < 2 |
| Time to log an event | < 30 seconds |
| Manual edits after AI parsing | < 10% |
| Missed recurring confirmations | < 5% |
| Duplicate recurring events | 0 |
| MCP tool failures | 0 |

At day 30: review this table, re-open the out-of-scope list, and decide
what — if anything — actually earned its place. That review becomes the
next spec, not this README.

---

## Build order (for Claude Code / anyone picking this up)

1. Schema exactly as written in `docs/SCHEMA_AND_FLOW_DESIGN.md` §2
2. Gemini-powered chat parser + 2x/day scheduler with correct trigger windows
3. Idempotent recurring-event generation (enforced by the DB constraint,
   not just app-code checks)
4. Stats via plain SQL — no precompute needed at this scale
5. Auth layer — before MCP tool #2, not after
6. MCP server wrapping the five tools, scoped per user
7. Web/mobile client — last, least differentiated part of this system

Ship 1–6. Use it daily for 30 days. Then decide what's next with real data,
not with a document written today.