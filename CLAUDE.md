# Finn — Personal Finance Tracker

Chat-first (Telegram) finance tracker: FastAPI backend, Neon Postgres, Gemini
parsing, MCP server for Claude/ChatGPT queries. All free-tier infra.

**Status:** spec frozen, no app code written yet. Read before writing any:
- `README.md` — architecture, repo structure, MCP tools, build order
- `docs/TECHNICAL_REPORT.md` — stack, packages, testing strategy, deploy steps
- `docs/SCHEMA_AND_FLOW_DESIGN.md` — DDL, ERD, state machine, MCP tool specs
- `AGENT.md` — **the live build tracker. Read it first every session, update
  it last every session. It is the single source of truth for what's done,
  what's next, and what's blocked.**

## Non-negotiables

- Everything is an `event` — one table, not five. Don't split it.
- One service, one repo, flat `app/` imports. No `apps/`, no `docker-compose.yml`.
- Follow `README.md`'s build order (schema → parser/scheduler → stats → auth
  → MCP → client). Auth lands before MCP tool #2, not after.
- Exactly 5 MCP tools for v1 (`log_event`, `today_summary`, `month_summary`,
  `category_summary`, `pending_events`). Don't add a 6th.
- Gemini only ever sees raw message text — never balances/history. Validate
  every field it returns before writing to the DB; treat model output as
  untrusted input.
- Don't build anything in the README's "out of scope for v1" list
  (per-user categories, OCR, forecasting, swappable-LLM abstraction, etc.)
  without the user explicitly reopening that decision.

## Working agreement for this repo

- **`AGENT.md` is mandatory, not optional documentation.** Before writing
  any code in a session: open `AGENT.md`, read the "Current State" and
  "Next Up" sections, confirm you're picking up where the last session left
  off. After finishing a unit of work (a step, a test file, a bugfix):
  update `AGENT.md`'s progress log with what was done, quantified — file
  count, test count, pass/fail, endpoints added — before moving to the next
  thing. Never leave `AGENT.md` stale relative to the actual repo state.
- **One step at a time, verified before moving on.** Don't write
  `scheduler_logic.py` and `mcp_server.py` in the same pass without running
  tests in between. The build order exists specifically so each layer is
  provably correct before the next depends on it.
- **Idempotency and auth tests are not optional polish.** Per
  `docs/TECHNICAL_REPORT.md` §5, `test_idempotency.py` gets written before
  the recurring-event generator, and `test_mcp.py`/`test_webhook.py` assert
  the unauthenticated-rejection path before the happy path. If you write the
  feature before the test in either case, stop and write the test first.
- **Migrations, not hand-edited schema.** Every schema change is a new
  Alembic revision (`alembic revision --autogenerate -m "..."`), never a
  manual `ALTER TABLE` run against Neon directly.
- **Secrets never touch the repo.** `.env` is git-ignored; only
  `.env.example` (documenting variable names, no real values) is committed.
  If you ever need a secret to test something, ask the user for it — don't
  invent a placeholder value and write it to a tracked file.
- **No scope creep without a logged decision.** If you're tempted to add
  something not in the v1 build order (a 6th MCP tool, a `people` table, a
  second LLM provider), don't — write it into `AGENT.md`'s "Parked Ideas"
  section instead and keep building v1.

## Commands (fill in once the app skeleton exists)

```bash
# local dev
source .venv/bin/activate
uvicorn app.main:app --reload

# tests (bare `uv run pytest` won't find the `app` package — use -m)
uv run python -m pytest                      # full suite
uv run python -m pytest tests/test_idempotency.py -v   # single file, verbose

# migrations
alembic revision --autogenerate -m "description"
alembic upgrade head

# manual scheduler trigger (local)
curl -X POST http://localhost:8000/trigger -H "Authorization: Bearer $TRIGGER_SECRET"
```

## Definition of done, per step

A step in the build order is not "done" when the code compiles — it's done
when:
1. The corresponding test file in `tests/` passes.
2. `AGENT.md` has been updated with what was built and the quantified result
   (e.g., "5/5 MCP tools implemented, 12/12 tests passing").
3. Nothing from a later build-order step was pulled forward to make this
   step's tests pass (no MCP code to make a stats test green, etc.).

If any of these three isn't true, the step isn't finished — keep working it
before starting the next one.