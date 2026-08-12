"""Ensure fixed notification templates exist.

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa

from app.notifications import DEFAULT_TEMPLATES


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for event_type, text_template in DEFAULT_TEMPLATES.items():
        connection.execute(
            sa.text(
                "INSERT IGNORE INTO notification_templates (event_type, text_template, updated_at) "
                "VALUES (:event_type, :text_template, CURRENT_TIMESTAMP)"
            ),
            {"event_type": event_type, "text_template": text_template},
        )


def downgrade() -> None:
    pass
