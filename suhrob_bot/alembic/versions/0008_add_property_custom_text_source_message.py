"""Add source message fields for custom property text

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("custom_text_source_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("properties", sa.Column("custom_text_source_message_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("properties", "custom_text_source_message_id")
    op.drop_column("properties", "custom_text_source_chat_id")
