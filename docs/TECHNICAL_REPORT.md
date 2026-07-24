# Personal Finance Tracker — Technical Report (v1, frozen for build)

**Status:** This is the version to build against. No further design review
until the 30-day usage checkpoint. Anything not in this document, or in
`02_SCHEMA_AND_FLOW_DESIGN.md`, is out of scope until real usage justifies it.

---

## 1. Stack overview

| Layer | Choice | Why this one | Free tier limit | Honest catch |
|---|---|---|---|---|
| Chat interface | **Telegram Bot API** | Free, webhooks, push, no app-store review | Effectively unlimited (personal use) | You're building a bot, not "an app" — correct scope for v1 |
| Backend | **FastAPI (Python 3.12)** on **Render free web service** | Matches Gemini's Python SDK, async-native, simple Git deploys | 750 free instance-hours/month | Spins down after 15 min idle, ~30–60s cold start on wake |
| Database access | **SQLAlchemy 2.0 (async) + Alembic** | Migrations tracked from commit 1 — cheap now, painful to retrofit | — | — |
| Database | **Neon (serverless Postgres)** — not Render Postgres | Real Postgres, branching, scales to zero **without deleting data**, ~1s resume | 0.5 GB storage, 100 compute-hrs/month | The one non-negotiable substitution — Render's free Postgres has been reported auto-deleted after 30–90 days idle. Unacceptable for a financial ledger |
| Scheduler | **GitHub Actions** (`cron:` trigger) — not Render Cron | Runs independent of Render's uptime/spin-down | 2,000 free Action-minutes/month (private repo) | `cron:` is best-effort, can lag several minutes under platform load |
| AI parsing | **Gemini API free tier** | Already the chosen provider, usable free quota for personal-scale parsing | RPM/RPD caps (check current quota page) | Nowhere near the limit at 2 pings + a few manual entries/day |
| MCP server | Same FastAPI app, mounted at `/mcp` | No separate hosting | Same as backend | ChatGPT's custom MCP connector needs a paid tier — Claude MCP works on free tier |
| Secrets | Render env vars + GitHub Actions repo secrets | Both free, encrypted at rest | — | Never commit `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL` |
| Repo/CI | **GitHub** (private repo, free) | Free private repos + Actions minutes, doubles as the cron trigger | 2,000 Action-minutes/month | Keep private — schema + mis-scoped secrets shouldn't be public |

**Deliberately not in this stack:** separate frontend framework, Docker,
Kubernetes, message queue, Redis, vector DB. All free-tier available —
none justified at this scale. Adding any of this now repeats the scope-creep
this whole project is designed to avoid.

---

## 2. Languages & runtime

| Component | Language / runtime | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI | Matches Gemini's Python SDK, async-native, minimal boilerplate |
| Database access | SQLAlchemy 2.0 (async) + Alembic | Migration history from day 1 |
| Scheduler | GitHub Actions YAML (no language — HTTP triggers) | Independent of backend uptime |
| Chat interface | Telegram Bot API (`httpx` or `python-telegram-bot`) | Zero-build chat UI |
| Tests | `pytest` + `pytest-asyncio` | Standard, no reason to deviate |

---

## 3. Dependencies (`requirements.txt`)

```
fastapi==0.115.*
uvicorn[standard]==0.32.*
sqlalchemy[asyncio]==2.0.*
asyncpg==0.30.*
alembic==1.14.*
pydantic==2.*
google-genai==1.*          # Gemini SDK -- verify current package name/version at build time
httpx==0.28.*               # Telegram API calls
python-dotenv==1.*
python-jose[cryptography]==3.*   # MCP/webhook auth tokens
pytest==8.*
pytest-asyncio==0.24.*
```

Pin exact versions at install time (`pip freeze > requirements.txt` after
first successful install) rather than trusting these ranges months later —
dependency drift is a real, if boring, risk for a project that runs
unattended.

---

## 4. Folder structure — flat, one deployable service

```
finance-tracker/
├── app/
│   ├── main.py            # FastAPI app: routes only, no business logic
│   ├── config.py          # env vars, loaded once; FEATURES flag dict
│   ├── db.py               # SQLAlchemy engine/session, Neon connection
│   ├── models.py           # SQLAlchemy models, mirrors the DDL exactly
│   ├── schemas.py          # Pydantic request/response shapes (incl. ParsedEvent)
│   ├── parser.py           # EventParser protocol + GeminiEventParser impl
│   ├── telegram.py         # webhook handling, message sending
│   ├── scheduler_logic.py  # "what's due today" logic, called by /trigger
│   ├── stats.py             # today/month/category summaries, via EventRepository
│   ├── repository.py        # EventRepository -- all SQL lives here
│   ├── mcp_server.py        # the 5 MCP tools, mounted at /mcp
│   └── logging_config.py    # structured JSON logging setup
│
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
│
├── tests/
│   ├── test_parser.py       # natural language -> structured event
│   ├── test_scheduler.py    # trigger windows, weekend/holiday drift
│   ├── test_idempotency.py  # duplicate triggers never duplicate events
│   ├── test_stats.py         # daily/weekly/monthly/category totals
│   ├── test_mcp.py           # auth + correct tool responses
│   └── test_webhook.py       # Telegram payload handling
│
├── .github/
│   └── workflows/
│       ├── daily-checkin.yml     # scheduler, 2x/day
│       └── nightly-backup.yml     # pg_dump -> GitHub artifact
│
├── docs/
│   ├── SPEC.md               # = 02_SCHEMA_AND_FLOW_DESIGN.md
│   └── DEPLOYMENT.md          # = this document, section 6-8
│
├── requirements.txt
├── .env.example                # documents required vars, never real secrets
└── README.md                   # = 03_README.md
```

No `apps/`, no `packages/`, no `docker-compose.yml`. One service, one repo,
flat imports. Reconsider structure only if this genuinely grows past a
single deployable unit — not before.

**Scheduler note:** Inngest (durable workflow engine) was evaluated as a
GitHub Actions replacement and rejected — the `pending → unconfirmed`
escalation it was proposed for is already fully expressed by the
`events.status` field plus the existing nightly cron scan. Revisit only if
a future workflow needs real branching or cross-restart durability that a
status column can't express.

### Core interfaces (accepted, minimal form)

```python
# app/parser.py
from typing import Protocol
from app.schemas import ParsedEvent

class EventParser(Protocol):
    async def parse(self, text: str) -> ParsedEvent: ...

class GeminiEventParser:
    async def parse(self, text: str) -> ParsedEvent:
        raw = await self._call_gemini(text)      # untrusted dict from the model
        return ParsedEvent.model_validate(raw)     # raises if the shape is wrong
```
No provider registry, no config-driven switching, no second implementation
until it's actually needed.

```python
# app/schemas.py
from pydantic import BaseModel
from decimal import Decimal
from typing import Literal

class ParsedEvent(BaseModel):
    direction: Literal["credit", "debit"]
    amount: Decimal
    category: str
    confidence: float
    notes: str | None = None
```
Gemini's raw output is untrusted input, exactly like a hostile HTTP request
body — `ParsedEvent.model_validate()` is the boundary where that stops being
true. Validation failure = `confidence = 0` case: ask a follow-up rather
than write malformed data.

```python
# app/repository.py
class EventRepository:
    def __init__(self, session): self.session = session
    async def create_event(self, parsed: ParsedEvent, **kwargs) -> Event: ...
    async def update_event(self, event_id, **fields) -> Event: ...
    async def get_pending_events(self, user_id) -> list[Event]: ...
    async def month_summary(self, user_id, month) -> dict: ...
```
`stats.py`, `scheduler_logic.py`, and `mcp_server.py` all go through this —
one place SQL lives, one place to fix it. Still a single file, not a folder.

```python
# app/config.py
FEATURES = {
    "mcp_enabled": True,
    "telegram_enabled": True,
    "scheduler_enabled": True,
    "experimental_parser_v2": False,
}
```
A dict, read from env vars in production — not a flag service or dashboard,
just a way to disable something mid-experiment without breaking daily use.

---

## 5. Testing strategy

Priority order — write these before, not after, the corresponding feature:

1. **Idempotency test first.** Cheapest test to write, protects the
   property that's hardest to debug in production (duplicate salary
   entries showing up weeks later).
2. **Parser tests** — fixed input strings ("lunch 120", "friend gave 500
   no reason", "EMI paid") with expected structured output. Run against the
   real Gemini API sparingly (cost/quota); mock for the rest.
3. **Scheduler tests** — trigger windows across month boundaries and
   weekends, since date math is where quiet bugs hide.
4. **Stats tests** — known fixture data in, known totals out. Refactors of
   `stats.py` must never silently change historical totals.
5. **MCP + webhook tests** — assert unauthenticated calls are rejected
   *before* asserting correct data is returned. Test the failure path first.

No coverage-percentage target — for a one-user tool, "does the money add up
correctly and does auth actually block strangers" covers what matters.

---

## 6. Migrations (Alembic)

```bash
alembic init alembic
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```
Every schema change after this is a new revision file, applied identically
locally and against Neon. Replaces "run schema.sql by hand" with a history
you can diff, roll back, and reason about.

---

## 7. Logging

```python
# app/logging_config.py
import logging, json, sys

class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "ts": self.formatTime(record),
            "level": record.levelname,
            "event_id": getattr(record, "event_id", None),
            "stage": getattr(record, "stage", None),   # telegram/parser/db/mcp
            "msg": record.getMessage(),
        })

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logging.getLogger().addHandler(handler)
```
Tag every log line through the pipeline (`telegram → parser → validation →
db → response`) with the same `event_id` — gives OpenTelemetry-level
debugging value, readable in Render's log viewer, at zero extra
infrastructure.

---

## 8. Backups

`.github/workflows/nightly-backup.yml`:
```yaml
name: nightly-backup
on:
  schedule:
    - cron: '0 20 * * *'   # ~1:30 AM IST
jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Dump Neon database
        run: |
          pg_dump "${{ secrets.DATABASE_URL }}" -F c -f backup.dump
      - name: Upload as artifact
        uses: actions/upload-artifact@v4
        with:
          name: db-backup-${{ github.run_id }}
          path: backup.dump
          retention-days: 30
```
30-day GitHub artifact retention is free and sufficient for a personal
project — this is a "don't lose a month of transactions to a fat-fingered
migration" safety net, not a compliance requirement.

---

## 9. Deployment topology

```
   Claude / ChatGPT (dev mode) / any MCP client
                    |
              MCP server (auth-scoped per user, /mcp route)
                    |
              FastAPI backend on Render  <-- all business logic, validation
                 /      \
        Gemini API      Neon (Postgres)
    (parse text only,   (source of truth,
     no DB access)       stats via plain SQL)

   GitHub Actions (cron) --> /healthz --> /trigger   (2x/day + nightly backup)
   Telegram webhook       --> /webhook                (real-time chat)
```
Neon is deliberately independent of Render's uptime — its own lifecycle,
never spun down or deleted for inactivity the way some free Postgres tiers
are.

### Step-by-step build order

**Step 1 — Provision, before any application code**
1. Create a Neon project (free), save `DATABASE_URL`.
2. Run the DDL from `02_SCHEMA_AND_FLOW_DESIGN.md` §2 against it.
3. Create a Telegram bot via @BotFather, get the bot token.
4. Get a Gemini API key from Google AI Studio.
5. Create a private GitHub repo, add all secrets under Settings → Secrets
   and variables → Actions.

**Step 2 — Backend (FastAPI on Render)**
Deploy: connect the repo to a new Render free web service. Build command
`pip install -r requirements.txt`, start command
`uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Add secrets as Render
env vars (not committed).

Register the Telegram webhook once:
```
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-render-url>/webhook"
```

**Step 3 — Scheduler (GitHub Actions, not Render Cron)**
`.github/workflows/daily-checkin.yml`:
```yaml
name: daily-checkin
on:
  schedule:
    - cron: '30 2 * * *'   # ~8:00 AM IST
    - cron: '30 14 * * *'  # ~8:00 PM IST
  workflow_dispatch: {}
jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - name: Wake and trigger
        run: |
          curl -s https://<your-render-url>/healthz || true   # absorbs cold start
          sleep 5
          curl -s -X POST https://<your-render-url>/trigger \
            -H "Authorization: Bearer ${{ secrets.TRIGGER_SECRET }}"
```
The two-request pattern exists specifically to absorb Render's cold start.

**Step 4 — MCP server**
Mount the 5 tools (see `02_SCHEMA_AND_FLOW_DESIGN.md` §5) as routes on the
same FastAPI app under `/mcp`, gated by a per-user API key. Point Claude's
(and ChatGPT's, if Developer Mode access exists) custom connector at
`https://<your-render-url>/mcp`.

**Step 5 — Verify against the success criterion**
Don't consider this "deployed" until, over real days:
- A Telegram message arrives on schedule, twice a day
- A recurring salary/EMI ping fires inside its window
- `month_summary()` returns correct numbers via Claude or ChatGPT
- A cold start doesn't silently drop the day's ping (test explicitly —
  trigger the workflow manually after 20+ min of Render inactivity)

---

## 10. Free-tier survival tactics

- **Don't keep Render "always warm"** with a keep-alive ping every 10
  minutes — burns free hours faster, doesn't solve anything the
  healthz→trigger pattern doesn't already solve for a twice-daily job.
- **Neon's 100 compute-hrs/month is not the bottleneck** at this scale.
  Becomes relevant only with frequent MCP queries or background jobs.
- **GitHub Actions `cron:` is best-effort** — expect ±10–15 min drift.
  This is exactly why `window_days` tolerance on recurring rules matters.
- **Monitor, don't assume.** A trivial `/healthz` check + a weekly glance
  at Render's dashboard beats discovering a silently-broken webhook weeks in.

| Signal | What it means | Cheapest fix |
|---|---|---|
| Neon storage nearing 0.5 GB | Lots of events — good sign | Neon Launch, ~$19/mo, only when hit |
| Render cold starts feel annoying | Want snappier replies | Render $7/mo starter removes spin-down |
| ChatGPT MCP connector unavailable | Needs paid ChatGPT tier | Use Claude's MCP support meanwhile |
| GitHub Actions minutes running low | Unlikely at 2 runs/day | 2,000 free min/mo is generous |

---

## 11. Consolidated build order (4 weeks)

**Week 1 — foundation:** Neon provisioned, Alembic initialized, schema
applied, FastAPI skeleton, Telegram webhook receiving and echoing messages.

**Week 2 — the actual product:** Gemini parser wired in (with tests),
events written correctly, `stats.py` returning correct daily/weekly/monthly/
category numbers.

**Week 3 — automation + interoperability:** GitHub Actions scheduler firing
on time, recurring-rule triggers working inside their window, idempotency
verified under manual duplicate-trigger testing, MCP server live and
queryable from Claude.

**Week 4 — live and measured:** Use it every day. Track the metrics table
(check-in completion rate, follow-up questions per event, time to log,
etc. — full table in `02_SCHEMA_AND_FLOW_DESIGN.md` §7). Fix friction as
observed, not as imagined in advance.

**At day 30:** review the metrics, re-open the out-of-scope list, decide
what — if anything — actually earned its place. Everything there stays out
until real usage says otherwise.
