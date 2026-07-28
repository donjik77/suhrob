"""add client_profiles.sendpulse_contact_id

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "client_profiles",
        sa.Column("sendpulse_contact_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_profiles", "sendpulse_contact_id")
