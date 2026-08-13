"""Add procurement values and event budget.

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("budget", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
    )
    op.add_column(
        "prizes",
        sa.Column("purchase_value", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
    )
    op.add_column(
        "redemption_items",
        sa.Column("purchase_value_snapshot", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("redemption_items", "purchase_value_snapshot")
    op.drop_column("prizes", "purchase_value")
    op.drop_column("events", "budget")
