"""TZ v3.0 schema: multi-bot, AI, balances, leads

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-07 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_enum(name: str, *values: str) -> None:
    vals = ", ".join(f"'{v}'" for v in values)
    op.execute(sa.text(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({vals}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$"
    ))


def upgrade() -> None:
    # ── New enums (idempotent) ───────────────────────────────────────
    _create_enum("subscriptiontype", "base", "instagram")
    _create_enum("paymentsource", "balance", "manual_proof")
    _create_enum("transactiontype", "topup", "subscription_charge", "instagram_charge", "refund")
    _create_enum("transactionstatus", "pending", "completed", "failed")
    _create_enum("postplatform", "telegram", "instagram")
    _create_enum("leadstatus", "new", "contacted", "showing_scheduled", "negotiation", "closed_won", "closed_lost")

    op.execute(sa.text("ALTER TYPE propertystatus ADD VALUE IF NOT EXISTS 'draft'"))
    op.execute(sa.text("ALTER TYPE paymentmethod ADD VALUE IF NOT EXISTS 'balance'"))

    # ── companies ───────────────────────────────────────────────────
    op.execute(sa.text("""
        ALTER TABLE companies
            ADD COLUMN IF NOT EXISTS bot_token          VARCHAR(255),
            ADD COLUMN IF NOT EXISTS bot_username       VARCHAR(64),
            ADD COLUMN IF NOT EXISTS bot_id             BIGINT,
            ADD COLUMN IF NOT EXISTS instagram_username VARCHAR(64),
            ADD COLUMN IF NOT EXISTS instagram_connected BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS trial_ends_at      TIMESTAMPTZ
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_companies_bot_token'
                           AND conrelid = 'companies'::regclass) THEN
                ALTER TABLE companies ADD CONSTRAINT uq_companies_bot_token UNIQUE (bot_token);
            END IF;
        END $$
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_companies_bot_username'
                           AND conrelid = 'companies'::regclass) THEN
                ALTER TABLE companies ADD CONSTRAINT uq_companies_bot_username UNIQUE (bot_username);
            END IF;
        END $$
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_companies_bot_id'
                           AND conrelid = 'companies'::regclass) THEN
                ALTER TABLE companies ADD CONSTRAINT uq_companies_bot_id UNIQUE (bot_id);
            END IF;
        END $$
    """))

    # ── users ────────────────────────────────────────────────────────
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_users_company_role ON users (company_id, role)"
    ))

    # ── properties ──────────────────────────────────────────────────
    op.execute(sa.text("""
        ALTER TABLE properties
            ADD COLUMN IF NOT EXISTS description_edited BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS location_lat       NUMERIC(10, 7),
            ADD COLUMN IF NOT EXISTS location_lng       NUMERIC(10, 7),
            ADD COLUMN IF NOT EXISTS features           JSON,
            ADD COLUMN IF NOT EXISTS instagram_post_id  VARCHAR(100),
            ADD COLUMN IF NOT EXISTS views_count        INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS contacts_count     INTEGER NOT NULL DEFAULT 0
    """))

    # ── property_media ───────────────────────────────────────────────
    op.execute(sa.text("""
        ALTER TABLE property_media
            ADD COLUMN IF NOT EXISTS is_main          BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN IF NOT EXISTS ai_quality_score NUMERIC(3, 1)
    """))

    # ── subscriptions ────────────────────────────────────────────────
    op.execute(sa.text("""
        ALTER TABLE subscriptions
            ADD COLUMN IF NOT EXISTS subscription_type subscriptiontype NOT NULL DEFAULT 'base',
            ADD COLUMN IF NOT EXISTS payment_source    paymentsource,
            ADD COLUMN IF NOT EXISTS auto_renewed      BOOLEAN NOT NULL DEFAULT false
    """))

    # ── scheduled_posts ──────────────────────────────────────────────
    op.execute(sa.text("""
        ALTER TABLE scheduled_posts
            ADD COLUMN IF NOT EXISTS platform   postplatform NOT NULL DEFAULT 'telegram',
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_scheduled_posts_status_at ON scheduled_posts (status, scheduled_at)"
    ))

    # ── notifications_log ────────────────────────────────────────────
    op.execute(sa.text("""
        ALTER TABLE notifications_log
            ADD COLUMN IF NOT EXISTS related_property_id INTEGER REFERENCES properties(id),
            ADD COLUMN IF NOT EXISTS message_text        TEXT
    """))
    # Convert notification_type from enum to varchar — idempotent (check data_type first)
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'notifications_log'
                  AND column_name = 'notification_type'
                  AND data_type = 'USER-DEFINED'
            ) THEN
                ALTER TABLE notifications_log
                    ALTER COLUMN notification_type TYPE VARCHAR(50)
                    USING notification_type::text;
            END IF;
        END $$
    """))

    # ── New tables (CREATE ... IF NOT EXISTS) ─────────────────────────
    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS user_balances (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL UNIQUE REFERENCES users(id),
            balance_usd NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
            balance_uzs NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
            updated_at  TIMESTAMPTZ    NOT NULL DEFAULT now()
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS balance_transactions (
            id                       SERIAL PRIMARY KEY,
            user_id                  INTEGER NOT NULL REFERENCES users(id),
            amount_usd               NUMERIC(10, 2),
            amount_uzs               NUMERIC(15, 2),
            transaction_type         transactiontype NOT NULL,
            payment_method           paymentmethod,
            description              TEXT,
            related_subscription_id  INTEGER REFERENCES subscriptions(id),
            status                   transactionstatus NOT NULL DEFAULT 'pending',
            payment_proof_file_id    VARCHAR(500),
            created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_balance_transactions_user_created "
        "ON balance_transactions (user_id, created_at)"
    ))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS client_profiles (
            id                  SERIAL PRIMARY KEY,
            user_id             INTEGER NOT NULL UNIQUE REFERENCES users(id),
            budget_min_usd      NUMERIC(10, 2),
            budget_max_usd      NUMERIC(10, 2),
            preferred_districts JSON,
            preferred_rooms     JSON,
            property_type       VARCHAR(20),
            purchase_timeline   VARCHAR(30),
            payment_method      VARCHAR(30),
            qualification_score INTEGER     NOT NULL DEFAULT 0,
            qualified_at        TIMESTAMPTZ,
            notes               TEXT,
            last_contact_at     TIMESTAMPTZ,
            follow_up_count     INTEGER     NOT NULL DEFAULT 0,
            unsubscribed        BOOLEAN     NOT NULL DEFAULT false,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS client_conversations (
            id          SERIAL PRIMARY KEY,
            user_id     INTEGER NOT NULL REFERENCES users(id),
            property_id INTEGER REFERENCES properties(id),
            role        VARCHAR(10) NOT NULL,
            message     TEXT        NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_client_conversations_user_created "
        "ON client_conversations (user_id, created_at)"
    ))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS client_alerts (
            id               SERIAL PRIMARY KEY,
            user_id          INTEGER NOT NULL REFERENCES users(id),
            location_district VARCHAR(100),
            price_max_usd    NUMERIC(10, 2),
            rooms            INTEGER,
            property_type    VARCHAR(20),
            is_active        BOOLEAN     NOT NULL DEFAULT true,
            last_notified_at TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS lead_assignments (
            id             SERIAL PRIMARY KEY,
            client_user_id INTEGER     NOT NULL REFERENCES users(id),
            agent_user_id  INTEGER     NOT NULL REFERENCES users(id),
            property_id    INTEGER     REFERENCES properties(id),
            status         leadstatus  NOT NULL DEFAULT 'new',
            notes          TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS lead_assignments"))
    op.execute(sa.text("DROP TABLE IF EXISTS client_alerts"))
    op.execute(sa.text("DROP TABLE IF EXISTS client_conversations"))
    op.execute(sa.text("DROP TABLE IF EXISTS client_profiles"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_balance_transactions_user_created"))
    op.execute(sa.text("DROP TABLE IF EXISTS balance_transactions"))
    op.execute(sa.text("DROP TABLE IF EXISTS user_balances"))

    op.execute(sa.text("DROP INDEX IF EXISTS ix_scheduled_posts_status_at"))
    op.execute(sa.text("ALTER TABLE scheduled_posts DROP COLUMN IF EXISTS created_at"))
    op.execute(sa.text("ALTER TABLE scheduled_posts DROP COLUMN IF EXISTS platform"))

    op.execute(sa.text("ALTER TABLE subscriptions DROP COLUMN IF EXISTS auto_renewed"))
    op.execute(sa.text("ALTER TABLE subscriptions DROP COLUMN IF EXISTS payment_source"))
    op.execute(sa.text("ALTER TABLE subscriptions DROP COLUMN IF EXISTS subscription_type"))

    op.execute(sa.text("ALTER TABLE property_media DROP COLUMN IF EXISTS ai_quality_score"))
    op.execute(sa.text("ALTER TABLE property_media DROP COLUMN IF EXISTS is_main"))

    op.execute(sa.text("ALTER TABLE properties DROP COLUMN IF EXISTS contacts_count"))
    op.execute(sa.text("ALTER TABLE properties DROP COLUMN IF EXISTS views_count"))
    op.execute(sa.text("ALTER TABLE properties DROP COLUMN IF EXISTS instagram_post_id"))
    op.execute(sa.text("ALTER TABLE properties DROP COLUMN IF EXISTS features"))
    op.execute(sa.text("ALTER TABLE properties DROP COLUMN IF EXISTS location_lng"))
    op.execute(sa.text("ALTER TABLE properties DROP COLUMN IF EXISTS location_lat"))
    op.execute(sa.text("ALTER TABLE properties DROP COLUMN IF EXISTS description_edited"))

    op.execute(sa.text("DROP INDEX IF EXISTS ix_users_company_role"))

    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_companies_bot_id'
                       AND conrelid = 'companies'::regclass) THEN
                ALTER TABLE companies DROP CONSTRAINT uq_companies_bot_id;
            END IF;
        END $$
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_companies_bot_username'
                       AND conrelid = 'companies'::regclass) THEN
                ALTER TABLE companies DROP CONSTRAINT uq_companies_bot_username;
            END IF;
        END $$
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_companies_bot_token'
                       AND conrelid = 'companies'::regclass) THEN
                ALTER TABLE companies DROP CONSTRAINT uq_companies_bot_token;
            END IF;
        END $$
    """))
    op.execute(sa.text("ALTER TABLE companies DROP COLUMN IF EXISTS trial_ends_at"))
    op.execute(sa.text("ALTER TABLE companies DROP COLUMN IF EXISTS instagram_connected"))
    op.execute(sa.text("ALTER TABLE companies DROP COLUMN IF EXISTS instagram_username"))
    op.execute(sa.text("ALTER TABLE companies DROP COLUMN IF EXISTS bot_id"))
    op.execute(sa.text("ALTER TABLE companies DROP COLUMN IF EXISTS bot_username"))
    op.execute(sa.text("ALTER TABLE companies DROP COLUMN IF EXISTS bot_token"))

    for name in ("leadstatus", "postplatform", "transactionstatus", "transactiontype",
                 "paymentsource", "subscriptiontype"):
        op.execute(sa.text(f"DROP TYPE IF EXISTS {name}"))
