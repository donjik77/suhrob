"""create tables

Revision ID: 0001
Revises:
Create Date: 2026-05-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    userrole = sa.Enum("client", "agent", "director", "developer", name="userrole")
    propertytype = sa.Enum("apartment", "house", "commercial", name="propertytype")
    propertystatus = sa.Enum("active", "sold", "hidden", name="propertystatus")
    filetype = sa.Enum("photo", "video", name="filetype")
    subscriptionstatus = sa.Enum(
        "active", "pending_payment", "expired", "blocked", name="subscriptionstatus"
    )
    paymentmethod = sa.Enum("click", "humo", "uzcard", "crypto", name="paymentmethod")
    scheduledpoststatus = sa.Enum("pending", "published", "failed", name="scheduledpoststatus")
    notificationtype = sa.Enum(
        "payment_reminder_3days", "payment_due", "blocked", "payment_received",
        name="notificationtype",
    )

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("telegram_channel_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(30), nullable=True),
        sa.Column("language", sa.String(10), nullable=False, server_default=sa.text("'uz'")),
        sa.Column(
            "role",
            userrole,
            nullable=False,
            server_default=sa.text("'client'"),
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "is_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_index("ix_users_telegram_user_id", "users", ["telegram_user_id"], unique=True)

    op.create_table(
        "properties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("location_district", sa.String(255), nullable=False),
        sa.Column("location_address", sa.String(500), nullable=True),
        sa.Column("rooms", sa.Integer(), nullable=False),
        sa.Column("floor", sa.Integer(), nullable=True),
        sa.Column("total_floors", sa.Integer(), nullable=True),
        sa.Column("area_sqm", sa.Numeric(8, 2), nullable=True),
        sa.Column("property_type", propertytype, nullable=False),
        sa.Column(
            "status",
            propertystatus,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("telegram_post_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_properties_company_status", "properties", ["company_id", "status"]
    )
    op.create_index(
        "ix_properties_search",
        "properties",
        ["location_district", "price_usd", "rooms"],
    )

    op.create_table(
        "property_media",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_id", sa.String(500), nullable=False),
        sa.Column("file_type", filetype, nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column(
            "order_index", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "search_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("location_district", sa.String(255), nullable=True),
        sa.Column("price_min_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_max_usd", sa.Numeric(12, 2), nullable=True),
        sa.Column("rooms", sa.Integer(), nullable=True),
        sa.Column(
            "results_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "client_favorites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "property_id", name="uq_favorite_user_property"),
    )

    op.create_table(
        "scheduled_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id",
            sa.Integer(),
            sa.ForeignKey("properties.id"),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            scheduledpoststatus,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id"),
            nullable=False,
        ),
        sa.Column(
            "price_usd",
            sa.Numeric(10, 2),
            nullable=False,
            server_default=sa.text("49.00"),
        ),
        sa.Column("price_uzs", sa.Numeric(15, 2), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            subscriptionstatus,
            nullable=False,
            server_default=sa.text("'pending_payment'"),
        ),
        sa.Column("payment_method", paymentmethod, nullable=True),
        sa.Column("payment_proof_file_id", sa.String(500), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "confirmed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_subscriptions_company_status", "subscriptions", ["company_id", "status"]
    )

    op.create_table(
        "notifications_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("notification_type", notificationtype, nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "related_subscription_id",
            sa.Integer(),
            sa.ForeignKey("subscriptions.id"),
            nullable=True,
        ),
    )

    op.create_table(
        "bot_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_table("bot_settings")
    op.drop_table("notifications_log")
    op.drop_table("subscriptions")
    op.drop_table("scheduled_posts")
    op.drop_table("client_favorites")
    op.drop_table("search_requests")
    op.drop_table("property_media")
    op.drop_table("properties")
    op.drop_table("users")
    op.drop_table("companies")

    for name in (
        "notificationtype",
        "scheduledpoststatus",
        "paymentmethod",
        "subscriptionstatus",
        "filetype",
        "propertystatus",
        "propertytype",
        "userrole",
    ):
        sa.Enum(name=name).drop(op.get_bind())
