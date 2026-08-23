"""Claim signatures on redemptions.

redemptions.signature stores the signed claim signature (trimmed mono PNG
data URL) collected on the admin claim tablet when a winner signs for pickup.

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("redemptions", sa.Column("signature", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("redemptions", "signature")
