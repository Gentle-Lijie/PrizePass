"""Add configurable notification routing rules.

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa

from app.notifications import default_routing_rules


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    if not sa.inspect(connection).has_table("notification_routing_rules"):
        op.create_table(
            "notification_routing_rules",
            sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
            sa.Column("event_type", sa.String(length=50), nullable=False),
            sa.Column(
                "channel",
                sa.Enum("email", "webhook", "email_poster", name="notification_routing_channel"),
                nullable=False,
            ),
            sa.Column(
                "recipient",
                sa.Enum("winner", "operations", "webhook", name="notification_recipient"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "event_type", "channel", "recipient", name="uq_notification_routing_rule"
            ),
        )
    for event_type, channel, recipient in default_routing_rules():
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
    op.drop_table("notification_routing_rules")
