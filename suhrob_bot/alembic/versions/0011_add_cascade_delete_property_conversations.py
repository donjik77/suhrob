"""add cascade delete on client_conversations.property_id

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "client_conversations_property_id_fkey",
        "client_conversations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "client_conversations_property_id_fkey",
        "client_conversations",
        "properties",
        ["property_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "client_conversations_property_id_fkey",
        "client_conversations",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "client_conversations_property_id_fkey",
        "client_conversations",
        "properties",
        ["property_id"],
        ["id"],
    )
