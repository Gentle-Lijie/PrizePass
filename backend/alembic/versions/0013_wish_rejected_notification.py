"""Seed wish_rejected notification templates and routing rules.

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa

from app.notifications import (
    DEFAULT_HTML_TEMPLATES,
    DEFAULT_TEMPLATES,
    default_routing_rules,
)


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

EVENT_TYPE = "wish_rejected"


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT IGNORE INTO notification_templates (event_type, text_template, html_template, updated_at) "
            "VALUES (:event_type, :text_template, :html_template, CURRENT_TIMESTAMP)"
        ),
        {
            "event_type": EVENT_TYPE,
            "text_template": DEFAULT_TEMPLATES[EVENT_TYPE],
            "html_template": DEFAULT_HTML_TEMPLATES[EVENT_TYPE],
        },
    )
    for event_type, channel, recipient in default_routing_rules():
        if event_type != EVENT_TYPE:
            continue
        connection.execute(
            sa.text(
                "INSERT IGNORE INTO notification_routing_rules "
                "(event_type, channel, recipient, updated_at) "
                "VALUES (:event_type, :channel, :recipient, CURRENT_TIMESTAMP)"
            ),
            {
                "event_type": event_type,
                "channel": channel.value,
                "recipient": recipient.value,
            },
        )


def downgrade() -> None:
    pass
