"""Add custom text and Telegram entities to properties

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("custom_text", sa.Text(), nullable=True))
    op.add_column("properties", sa.Column("custom_text_entities_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("properties", "custom_text_entities_json")
    op.drop_column("properties", "custom_text")
