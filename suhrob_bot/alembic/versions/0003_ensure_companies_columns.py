"""Ensure companies table has all required columns (idempotent repair)

If migration 0002 previously failed (e.g. due to the missing USING clause on
ALTER COLUMN), this migration adds the missing companies columns using
ADD COLUMN IF NOT EXISTS so it is safe on any DB state.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-07 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All ADD COLUMN IF NOT EXISTS — completely safe if 0002 already ran.
    op.execute(sa.text("""
        ALTER TABLE companies
            ADD COLUMN IF NOT EXISTS bot_token        VARCHAR(255),
            ADD COLUMN IF NOT EXISTS bot_username     VARCHAR(64),
            ADD COLUMN IF NOT EXISTS bot_id           BIGINT,
            ADD COLUMN IF NOT EXISTS instagram_username VARCHAR(64),
            ADD COLUMN IF NOT EXISTS instagram_connected BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS trial_ends_at    TIMESTAMPTZ
    """))

    # Unique constraints — each wrapped in a DO block so duplicate-object is ignored.
    op.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_companies_bot_token'
                  AND conrelid = 'companies'::regclass
            ) THEN
                ALTER TABLE companies
                    ADD CONSTRAINT uq_companies_bot_token UNIQUE (bot_token);
            END IF;
        END $$
    """))

    op.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_companies_bot_username'
                  AND conrelid = 'companies'::regclass
            ) THEN
                ALTER TABLE companies
                    ADD CONSTRAINT uq_companies_bot_username UNIQUE (bot_username);
            END IF;
        END $$
    """))

    op.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_companies_bot_id'
                  AND conrelid = 'companies'::regclass
            ) THEN
                ALTER TABLE companies
                    ADD CONSTRAINT uq_companies_bot_id UNIQUE (bot_id);
            END IF;
        END $$
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_companies_bot_id'
                  AND conrelid = 'companies'::regclass
            ) THEN
                ALTER TABLE companies DROP CONSTRAINT uq_companies_bot_id;
            END IF;
        END $$
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_companies_bot_username'
                  AND conrelid = 'companies'::regclass
            ) THEN
                ALTER TABLE companies DROP CONSTRAINT uq_companies_bot_username;
            END IF;
        END $$
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_companies_bot_token'
                  AND conrelid = 'companies'::regclass
            ) THEN
                ALTER TABLE companies DROP CONSTRAINT uq_companies_bot_token;
            END IF;
        END $$
    """))
    op.drop_column("companies", "trial_ends_at")
    op.drop_column("companies", "instagram_connected")
    op.drop_column("companies", "instagram_username")
    op.drop_column("companies", "bot_id")
    op.drop_column("companies", "bot_username")
    op.drop_column("companies", "bot_token")
