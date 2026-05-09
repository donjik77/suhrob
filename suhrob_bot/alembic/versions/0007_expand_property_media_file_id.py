"""Expand property media file_id length

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "property_media",
        "file_id",
        existing_type=sa.String(length=255),
        type_=sa.String(length=500),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "property_media",
        "file_id",
        existing_type=sa.String(length=500),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
