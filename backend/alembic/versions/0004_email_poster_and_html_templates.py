"""Add email-poster channel and HTML notification content.

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa

from app.notifications import DEFAULT_HTML_TEMPLATES


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


old_channels = sa.Enum("email", "webhook", name="notification_channel")
new_channels = sa.Enum("email", "webhook", "email_poster", name="notification_channel")


def upgrade() -> None:
    connection = op.get_bind()
    template_columns = {
        column["name"] for column in sa.inspect(connection).get_columns("notification_templates")
    }
    if "html_template" not in template_columns:
        op.add_column("notification_templates", sa.Column("html_template", sa.Text(), nullable=True))
    for event_type, html_template in DEFAULT_HTML_TEMPLATES.items():
        connection.execute(
            sa.text(
                "UPDATE notification_templates SET html_template = :html_template "
                "WHERE event_type = :event_type"
            ),
            {"event_type": event_type, "html_template": html_template},
        )
    job_columns = {
        column["name"]: column for column in sa.inspect(connection).get_columns("notification_jobs")
    }
    if "html_rendered" not in job_columns:
        op.add_column("notification_jobs", sa.Column("html_rendered", sa.Text(), nullable=True))
    channel_values = set(getattr(job_columns["channel"]["type"], "enums", ()))
    if "email_poster" not in channel_values:
        op.alter_column(
            "notification_jobs",
            "channel",
            existing_type=old_channels,
            type_=new_channels,
            existing_nullable=False,
        )


def downgrade() -> None:
    op.execute("DELETE FROM notification_jobs WHERE channel = 'email_poster'")
    op.alter_column(
        "notification_jobs",
        "channel",
        existing_type=new_channels,
        type_=old_channels,
        existing_nullable=False,
    )
    op.drop_column("notification_jobs", "html_rendered")
    op.drop_column("notification_templates", "html_template")
