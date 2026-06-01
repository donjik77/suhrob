"""add new_client notification type

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'new_client'")


def downgrade() -> None:
    # PostgreSQL не поддерживает удаление значений enum без пересоздания типа.
    pass
