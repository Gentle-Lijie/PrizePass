"""Global prize pool, winner award names, and purchase order tables.

- winners.award_name: award title (e.g. 一等奖) surfaced in emails and exports.
- prizes.event_id dropped: the prize pool is now shared by all events.
- event_prize_availability: each event selects which prizes from the global
  pool are available for its winners to redeem.
- purchase_orders / _items / _attachments: reimbursement workflow with
  transaction screenshots, invoice PDFs and zipped package downloads.

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa

from app.models import (
    PurchaseOrder,
    PurchaseOrderAttachment,
    PurchaseOrderItem,
)
from app.notifications import DEFAULT_HTML_TEMPLATES, DEFAULT_TEMPLATES


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # 1. Winner award names.
    winner_columns = {column["name"] for column in inspector.get_columns("winners")}
    if "award_name" not in winner_columns:
        op.add_column("winners", sa.Column("award_name", sa.String(200), nullable=True))

    # 2. Create availability table for event-prize selection.
    event_prize_availability = sa.Table(
        "event_prize_availability",
        sa.MetaData(),
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("events.id"), primary_key=True),
        sa.Column("prize_id", sa.BigInteger(), sa.ForeignKey("prizes.id"), primary_key=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    event_prize_availability.create(bind=connection, checkfirst=True)

    # 3. Migrate existing prize->event relationships to the availability table.
    prize_columns = {column["name"] for column in inspector.get_columns("prizes")}
    if "event_id" in prize_columns:
        # Copy existing relationships: each prize is available for its original event.
        connection.execute(
            sa.text(
                "INSERT INTO event_prize_availability (event_id, prize_id) "
                "SELECT event_id, id FROM prizes WHERE event_id IS NOT NULL"
            )
        )
        # Drop the event_id column from prizes table.
        constraints = connection.execute(
            sa.text(
                "SELECT DISTINCT kcu.CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE kcu "
                "WHERE kcu.TABLE_SCHEMA = DATABASE() AND kcu.TABLE_NAME = 'prizes' "
                "AND kcu.COLUMN_NAME = 'event_id' AND kcu.REFERENCED_TABLE_NAME IS NOT NULL"
            )
        ).scalars().all()
        for name in constraints:
            op.drop_constraint(name, "prizes", type_="foreignkey")
        op.drop_column("prizes", "event_id")

    # 4. Purchase order tables - drop old tables first to ensure correct schema.
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    # Drop old tables if they exist (may have outdated schema from previous attempts).
    if "purchase_order_attachments" in existing_tables:
        op.drop_table("purchase_order_attachments")
    if "purchase_order_items" in existing_tables:
        op.drop_table("purchase_order_items")
    if "purchase_orders" in existing_tables:
        op.drop_table("purchase_orders")

    # Create fresh tables with correct schema.
    PurchaseOrder.__table__.create(bind=connection)
    PurchaseOrderItem.__table__.create(bind=connection)
    PurchaseOrderAttachment.__table__.create(bind=connection)

    # 5. code_issued templates gain the {{award_name}} variable.
    connection.execute(
        sa.text(
            "UPDATE notification_templates SET text_template = :text_template, html_template = :html_template "
            "WHERE event_type = 'code_issued'"
        ),
        {
            "text_template": DEFAULT_TEMPLATES["code_issued"],
            "html_template": DEFAULT_HTML_TEMPLATES["code_issued"],
        },
    )


def downgrade() -> None:
    connection = op.get_bind()
    PurchaseOrderAttachment.__table__.drop(bind=connection, checkfirst=True)
    PurchaseOrderItem.__table__.drop(bind=connection, checkfirst=True)
    PurchaseOrder.__table__.drop(bind=connection, checkfirst=True)
    op.add_column(
        "prizes",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.ForeignKey("events.id"),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.drop_column("winners", "award_name")
    op.drop_table("event_prize_availability")
