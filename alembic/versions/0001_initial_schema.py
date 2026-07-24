"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-24

DDL copied exactly from docs/SCHEMA_AND_FLOW_DESIGN.md section 2 (frozen spec).
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.execute("""
        CREATE TABLE users (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name        TEXT NOT NULL,
            timezone    TEXT NOT NULL DEFAULT 'Asia/Kolkata',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE accounts (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id     UUID NOT NULL REFERENCES users(id),
            name        TEXT NOT NULL,
            kind        TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE categories (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            name        TEXT NOT NULL UNIQUE,
            direction   TEXT NOT NULL CHECK (direction IN ('credit','debit','either'))
        )
    """)

    op.execute("""
        CREATE TABLE recurring_rules (
            id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id          UUID NOT NULL REFERENCES users(id),
            label            TEXT NOT NULL,
            category_id      UUID NOT NULL REFERENCES categories(id),
            expected_amount  NUMERIC(12,2) NOT NULL,
            direction        TEXT NOT NULL CHECK (direction IN ('credit','debit')),
            day_of_month     SMALLINT NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
            window_days      SMALLINT NOT NULL DEFAULT 2,
            active           BOOLEAN NOT NULL DEFAULT true,
            active_from      DATE NOT NULL DEFAULT CURRENT_DATE,
            active_until     DATE
        )
    """)

    op.execute("""
        CREATE TABLE events (
            id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            user_id            UUID NOT NULL REFERENCES users(id),
            direction          TEXT NOT NULL CHECK (direction IN ('credit','debit')),
            recurring_rule_id  UUID REFERENCES recurring_rules(id),
            status             TEXT NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','confirmed','corrected','unconfirmed')),
            expected_amount    NUMERIC(12,2),
            actual_amount      NUMERIC(12,2),
            expected_at        TIMESTAMPTZ,
            event_at           TIMESTAMPTZ,
            account_id         UUID REFERENCES accounts(id),
            category_id        UUID NOT NULL REFERENCES categories(id),
            source             TEXT NOT NULL CHECK (source IN ('manual','scheduled','import')),
            raw_text           TEXT,
            notes              TEXT,
            confidence         NUMERIC(3,2),
            metadata           JSONB,
            version            INT NOT NULL DEFAULT 1,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # date_trunc('month', timestamptz) is STABLE, not IMMUTABLE (depends on
    # session timezone) -- Postgres rejects it in an index expression.
    # expected_at AT TIME ZONE 'UTC' collapses to a plain (UTC) timestamp
    # first, whose date_trunc IS immutable. Same partial-unique semantics as
    # the spec, adjusted to actually run on real Postgres.
    op.execute("""
        CREATE UNIQUE INDEX ux_recurring_cycle
            ON events (recurring_rule_id, date_trunc('month', expected_at AT TIME ZONE 'UTC'))
            WHERE recurring_rule_id IS NOT NULL
    """)

    op.execute("""
        CREATE TABLE event_history (
            id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            event_id     UUID NOT NULL REFERENCES events(id),
            field_name   TEXT NOT NULL,
            old_value    TEXT,
            new_value    TEXT,
            reason       TEXT,
            changed_by   TEXT NOT NULL DEFAULT 'user',
            changed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("CREATE INDEX idx_events_user_time ON events (user_id, event_at DESC)")
    op.execute(
        "CREATE INDEX idx_events_status ON events (user_id, status) "
        "WHERE status IN ('pending','unconfirmed')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS event_history")
    op.execute("DROP TABLE IF EXISTS events")
    op.execute("DROP TABLE IF EXISTS recurring_rules")
    op.execute("DROP TABLE IF EXISTS categories")
    op.execute("DROP TABLE IF EXISTS accounts")
    op.execute("DROP TABLE IF EXISTS users")
