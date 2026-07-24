"""Schema tests: run the Alembic migration against TEST_DATABASE_URL and
assert every table, column, and constraint from
`docs/SCHEMA_AND_FLOW_DESIGN.md` §2 exists exactly as documented.

Requires TEST_DATABASE_URL (a disposable/scratch Postgres branch) to be set
in the environment -- never point this at the real DATABASE_URL. See
DECISIONS.md for why this isn't in .env.
"""

import pytest
import sqlalchemy as sa

from tests.conftest import requires_test_db

pytestmark = requires_test_db


@pytest.fixture
async def conn(db_session):
    """A raw AsyncConnection off the same (truncated-clean) session/engine
    tests/conftest.py already sets up, for schema inspection + raw SQL."""
    yield await db_session.connection()


EXPECTED_TABLES = {
    "users", "accounts", "categories", "recurring_rules", "events", "event_history",
}


def _inspect_tables(sync_conn):
    return set(sa.inspect(sync_conn).get_table_names())


def _inspect_columns(sync_conn, table_name):
    return {c["name"] for c in sa.inspect(sync_conn).get_columns(table_name)}


@pytest.mark.anyio
async def test_all_six_tables_exist(conn):
    tables = await conn.run_sync(_inspect_tables)
    assert EXPECTED_TABLES <= tables


@pytest.mark.anyio
async def test_events_table_has_documented_columns(conn):
    columns = await conn.run_sync(_inspect_columns, "events")
    assert columns == {
        "id", "user_id", "direction", "recurring_rule_id", "status",
        "expected_amount", "actual_amount", "expected_at", "event_at",
        "account_id", "category_id", "source", "raw_text", "notes",
        "confidence", "metadata", "version", "created_at", "updated_at",
    }


@pytest.mark.anyio
async def test_events_status_check_constraint_rejects_bad_value(conn):
    user_id = (await conn.execute(sa.text(
        "INSERT INTO users (name) VALUES ('t') RETURNING id"
    ))).scalar()
    category_id = (await conn.execute(sa.text(
        "INSERT INTO categories (name, direction) VALUES ('Food', 'debit') RETURNING id"
    ))).scalar()
    await conn.commit()

    with pytest.raises(sa.exc.DBAPIError):
        await conn.execute(sa.text(
            "INSERT INTO events (user_id, direction, status, source, category_id) "
            "VALUES (:user_id, 'debit', 'not-a-real-status', 'manual', :category_id)"
        ), {"user_id": user_id, "category_id": category_id})
        await conn.commit()


@pytest.mark.anyio
async def test_ux_recurring_cycle_rejects_second_row_same_month(conn):
    user_id = (await conn.execute(sa.text(
        "INSERT INTO users (name) VALUES ('t2') RETURNING id"
    ))).scalar()
    category_id = (await conn.execute(sa.text(
        "INSERT INTO categories (name, direction) VALUES ('Salary', 'credit') RETURNING id"
    ))).scalar()
    rule_id = (await conn.execute(sa.text(
        "INSERT INTO recurring_rules "
        "(user_id, label, category_id, expected_amount, direction, day_of_month) "
        "VALUES (:user_id, 'Salary', :category_id, 1000, 'credit', 28) RETURNING id"
    ), {"user_id": user_id, "category_id": category_id})).scalar()
    await conn.commit()

    await conn.execute(sa.text(
        "INSERT INTO events "
        "(user_id, direction, recurring_rule_id, status, source, category_id, expected_at) "
        "VALUES (:user_id, 'credit', :rule_id, 'pending', 'scheduled', :category_id, '2026-07-28T00:00:00Z')"
    ), {"user_id": user_id, "rule_id": rule_id, "category_id": category_id})
    await conn.commit()

    with pytest.raises(sa.exc.IntegrityError):
        await conn.execute(sa.text(
            "INSERT INTO events "
            "(user_id, direction, recurring_rule_id, status, source, category_id, expected_at) "
            "VALUES (:user_id, 'credit', :rule_id, 'pending', 'scheduled', :category_id, '2026-07-29T00:00:00Z')"
        ), {"user_id": user_id, "rule_id": rule_id, "category_id": category_id})
        await conn.commit()
