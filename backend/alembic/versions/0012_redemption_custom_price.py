"""Add expected price to custom prize redemptions.

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from app.notifications import DEFAULT_HTML_TEMPLATES, DEFAULT_TEMPLATES


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("redemptions", sa.Column("custom_price", mysql.INTEGER(unsigned=True), nullable=True))
    # The wish_submitted templates were seeded moments ago by 0011; refresh them
    # to include the new price variable.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE notification_templates SET text_template = :text_template, html_template = :html_template "
            "WHERE event_type = 'wish_submitted'"
        ),
        {
            "text_template": DEFAULT_TEMPLATES["wish_submitted"],
            "html_template": DEFAULT_HTML_TEMPLATES["wish_submitted"],
        },
    )


def downgrade() -> None:
    op.drop_column("redemptions", "custom_price")
