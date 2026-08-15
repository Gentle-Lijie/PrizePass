"""Add on-shelf flag to prizes.

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prizes", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")))


def downgrade() -> None:
    op.drop_column("prizes", "is_active")
