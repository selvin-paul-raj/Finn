"""add users.telegram_chat_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-24

/trigger's scheduled reminders (recurring salary/EMI/SIP pings) need to know
which Telegram chat to send to. The frozen DDL in
docs/SCHEMA_AND_FLOW_DESIGN.md section 2 has no such column -- this was a
real gap, not a design choice, so it's an additive migration rather than a
hand-edited schema change. See DECISIONS.md.
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.create_unique_constraint("uq_users_telegram_chat_id", "users", ["telegram_chat_id"])


def downgrade() -> None:
    op.drop_constraint("uq_users_telegram_chat_id", "users", type_="unique")
    op.drop_column("users", "telegram_chat_id")
