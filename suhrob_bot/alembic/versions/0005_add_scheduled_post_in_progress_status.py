"""Add in_progress status for scheduled posts

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TYPE scheduledpoststatus ADD VALUE IF NOT EXISTS 'in_progress'"))


def downgrade() -> None:
    # PostgreSQL cannot remove enum values safely without recreating the type.
    pass
