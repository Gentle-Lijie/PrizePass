"""Add custom prize fields to redemptions and seed wish_submitted notification.

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa

from app.notifications import (
    DEFAULT_HTML_TEMPLATES,
    DEFAULT_TEMPLATES,
    default_routing_rules,
)


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

EVENT_TYPE = "wish_submitted"


def upgrade() -> None:
    op.add_column("redemptions", sa.Column("custom_name", sa.String(200), nullable=True))
    op.add_column("redemptions", sa.Column("custom_url", sa.Text(), nullable=True))
    op.add_column("redemptions", sa.Column("custom_note", sa.Text(), nullable=True))
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
    op.drop_column("redemptions", "custom_note")
    op.drop_column("redemptions", "custom_url")
    op.drop_column("redemptions", "custom_name")
