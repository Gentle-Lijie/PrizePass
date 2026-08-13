"""Allow prize stock to become negative for back-orders.

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "prizes",
        "stock",
        existing_type=mysql.INTEGER(unsigned=True),
        type_=sa.BigInteger(),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Negative values represent outstanding procurement and cannot fit an unsigned column.
    op.execute("UPDATE prizes SET stock = 0 WHERE stock < 0")
    op.alter_column(
        "prizes",
        "stock",
        existing_type=sa.BigInteger(),
        type_=mysql.INTEGER(unsigned=True),
        existing_nullable=False,
    )
