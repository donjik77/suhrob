"""Scope Telegram user identity by company

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-08 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Old schema made telegram_user_id globally unique, which leaks roles across
    # company bots. Drop both the implicit unique constraint and explicit index.
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'users_telegram_user_id_key'
                  AND conrelid = 'users'::regclass
            ) THEN
                ALTER TABLE users DROP CONSTRAINT users_telegram_user_id_key;
            END IF;
        END $$
    """))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_telegram_user_id"))

    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_users_telegram_user_id "
        "ON users (telegram_user_id)"
    ))
    op.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_company_active
        ON users (telegram_user_id, company_id)
        WHERE company_id IS NOT NULL AND telegram_user_id <> 0
    """))
    op.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_global_active
        ON users (telegram_user_id)
        WHERE company_id IS NULL AND telegram_user_id <> 0
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_telegram_company_active"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_telegram_global_active"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_telegram_user_id"))
    op.execute(sa.text("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_users_telegram_user_id
        ON users (telegram_user_id)
    """))
