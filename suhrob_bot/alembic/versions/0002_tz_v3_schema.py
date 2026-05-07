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
    op.execute(sa.text(f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({vals}); EXCEPTION WHEN duplicate_object THEN NULL; END $$"))


def upgrade() -> None:
    # ── New enums (idempotent via DO block) ──────────────────────────
    _create_enum("subscriptiontype", "base", "instagram")
    _create_enum("paymentsource", "balance", "manual_proof")
    _create_enum("transactiontype", "topup", "subscription_charge", "instagram_charge", "refund")
    _create_enum("transactionstatus", "pending", "completed", "failed")
    _create_enum("postplatform", "telegram", "instagram")
    _create_enum("leadstatus", "new", "contacted", "showing_scheduled", "negotiation", "closed_won", "closed_lost")

    # Add "draft" to existing propertystatus enum (PostgreSQL ALTER TYPE)
    op.execute("ALTER TYPE propertystatus ADD VALUE IF NOT EXISTS 'draft'")

    # Add "balance" to existing paymentmethod enum
    op.execute("ALTER TYPE paymentmethod ADD VALUE IF NOT EXISTS 'balance'")

    # ── Alter companies ──────────────────────────────────────────────
    op.add_column("companies", sa.Column("bot_token", sa.String(255), nullable=True))
    op.add_column("companies", sa.Column("bot_username", sa.String(64), nullable=True))
    op.add_column("companies", sa.Column("bot_id", sa.BigInteger(), nullable=True))
    op.add_column("companies", sa.Column("instagram_username", sa.String(64), nullable=True))
    op.add_column("companies", sa.Column("instagram_connected", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("companies", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_companies_bot_token", "companies", ["bot_token"])
    op.create_unique_constraint("uq_companies_bot_username", "companies", ["bot_username"])
    op.create_unique_constraint("uq_companies_bot_id", "companies", ["bot_id"])

    # ── Alter users ──────────────────────────────────────────────────
    op.create_index("ix_users_company_role", "users", ["company_id", "role"])

    # ── Alter properties ─────────────────────────────────────────────
    op.add_column("properties", sa.Column("description_edited", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("properties", sa.Column("location_lat", sa.Numeric(10, 7), nullable=True))
    op.add_column("properties", sa.Column("location_lng", sa.Numeric(10, 7), nullable=True))
    op.add_column("properties", sa.Column("features", sa.JSON(), nullable=True))
    op.add_column("properties", sa.Column("instagram_post_id", sa.String(100), nullable=True))
    op.add_column("properties", sa.Column("views_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("properties", sa.Column("contacts_count", sa.Integer(), nullable=False, server_default=sa.text("0")))

    # ── Alter property_media ─────────────────────────────────────────
    op.add_column("property_media", sa.Column("is_main", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("property_media", sa.Column("ai_quality_score", sa.Numeric(3, 1), nullable=True))

    # ── Alter subscriptions ──────────────────────────────────────────
    op.add_column("subscriptions", sa.Column(
        "subscription_type",
        sa.Enum("base", "instagram", name="subscriptiontype", create_type=False),
        nullable=False, server_default=sa.text("'base'")
    ))
    op.add_column("subscriptions", sa.Column(
        "payment_source",
        sa.Enum("balance", "manual_proof", name="paymentsource", create_type=False),
        nullable=True
    ))
    op.add_column("subscriptions", sa.Column(
        "auto_renewed", sa.Boolean(), nullable=False, server_default=sa.text("false")
    ))

    # ── Alter scheduled_posts ────────────────────────────────────────
    op.add_column("scheduled_posts", sa.Column(
        "platform",
        sa.Enum("telegram", "instagram", name="postplatform", create_type=False),
        nullable=False, server_default=sa.text("'telegram'")
    ))
    op.add_column("scheduled_posts", sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    ))
    op.create_index("ix_scheduled_posts_status_at", "scheduled_posts", ["status", "scheduled_at"])

    # ── Alter notifications_log ──────────────────────────────────────
    op.add_column("notifications_log", sa.Column("related_property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True))
    op.add_column("notifications_log", sa.Column("message_text", sa.Text(), nullable=True))
    # Change notification_type to String to support more types without enum migrations
    # postgresql_using is required because PostgreSQL cannot auto-cast ENUM → varchar
    op.alter_column(
        "notifications_log", "notification_type",
        type_=sa.String(50),
        existing_type=sa.Enum(
            "payment_reminder_3days", "payment_due", "blocked", "payment_received",
            name="notificationtype",
        ),
        existing_nullable=False,
        postgresql_using="notification_type::text",
    )

    # ── New tables ───────────────────────────────────────────────────

    op.create_table(
        "user_balances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("balance_usd", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("balance_uzs", sa.Numeric(15, 2), nullable=False, server_default=sa.text("0.00")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "balance_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("amount_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("amount_uzs", sa.Numeric(15, 2), nullable=True),
        sa.Column("transaction_type", sa.Enum(
            "topup", "subscription_charge", "instagram_charge", "refund",
            name="transactiontype", create_type=False
        ), nullable=False),
        sa.Column("payment_method", sa.Enum(
            "click", "humo", "uzcard", "crypto", "balance",
            name="paymentmethod", create_type=False
        ), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("related_subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id"), nullable=True),
        sa.Column("status", sa.Enum(
            "pending", "completed", "failed",
            name="transactionstatus", create_type=False
        ), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("payment_proof_file_id", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_balance_transactions_user_created", "balance_transactions", ["user_id", "created_at"])

    op.create_table(
        "client_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("budget_min_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("budget_max_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("preferred_districts", sa.JSON(), nullable=True),
        sa.Column("preferred_rooms", sa.JSON(), nullable=True),
        sa.Column("property_type", sa.String(20), nullable=True),
        sa.Column("purchase_timeline", sa.String(30), nullable=True),
        sa.Column("payment_method", sa.String(30), nullable=True),
        sa.Column("qualification_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("qualified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_contact_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("follow_up_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unsubscribed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "client_conversations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_client_conversations_user_created", "client_conversations", ["user_id", "created_at"])

    op.create_table(
        "client_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("location_district", sa.String(100), nullable=True),
        sa.Column("price_max_usd", sa.Numeric(10, 2), nullable=True),
        sa.Column("rooms", sa.Integer(), nullable=True),
        sa.Column("property_type", sa.String(20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "lead_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("agent_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("status", sa.Enum(
            "new", "contacted", "showing_scheduled", "negotiation",
            "closed_won", "closed_lost",
            name="leadstatus", create_type=False
        ), nullable=False, server_default=sa.text("'new'")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("lead_assignments")
    op.drop_table("client_alerts")
    op.drop_table("client_conversations")
    op.drop_table("client_profiles")
    op.drop_index("ix_balance_transactions_user_created", "balance_transactions")
    op.drop_table("balance_transactions")
    op.drop_table("user_balances")

    op.drop_index("ix_scheduled_posts_status_at", "scheduled_posts")
    op.drop_column("scheduled_posts", "created_at")
    op.drop_column("scheduled_posts", "platform")

    op.drop_column("subscriptions", "auto_renewed")
    op.drop_column("subscriptions", "payment_source")
    op.drop_column("subscriptions", "subscription_type")

    op.drop_column("property_media", "ai_quality_score")
    op.drop_column("property_media", "is_main")

    op.drop_column("properties", "contacts_count")
    op.drop_column("properties", "views_count")
    op.drop_column("properties", "instagram_post_id")
    op.drop_column("properties", "features")
    op.drop_column("properties", "location_lng")
    op.drop_column("properties", "location_lat")
    op.drop_column("properties", "description_edited")

    op.drop_index("ix_users_company_role", "users")

    op.drop_constraint("uq_companies_bot_id", "companies")
    op.drop_constraint("uq_companies_bot_username", "companies")
    op.drop_constraint("uq_companies_bot_token", "companies")
    op.drop_column("companies", "trial_ends_at")
    op.drop_column("companies", "instagram_connected")
    op.drop_column("companies", "instagram_username")
    op.drop_column("companies", "bot_id")
    op.drop_column("companies", "bot_username")
    op.drop_column("companies", "bot_token")

    for name in ("leadstatus", "postplatform", "transactionstatus", "transactiontype", "paymentsource", "subscriptiontype"):
        sa.Enum(name=name).drop(op.get_bind(), checkfirst=True)
