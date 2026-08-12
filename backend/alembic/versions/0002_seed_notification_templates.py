"""Seed fixed notification templates.

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa

from app.notifications import DEFAULT_TEMPLATES


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = sa.table(
        "notification_templates",
        sa.column("event_type", sa.String),
        sa.column("text_template", sa.Text),
    )
    op.bulk_insert(
        table,
        [
            {"event_type": event_type, "text_template": text_template}
            for event_type, text_template in DEFAULT_TEMPLATES.items()
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM notification_templates WHERE event_type IN :event_types").bindparams(
            sa.bindparam("event_types", expanding=True, value=list(DEFAULT_TEMPLATES))
        )
    )
