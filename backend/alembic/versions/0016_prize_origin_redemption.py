"""Wish-generated prizes: prizes.origin_redemption_id, procuring status, backfill.

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa

from app.notifications import (
    DEFAULT_HTML_TEMPLATES,
    DEFAULT_TEMPLATES,
    default_routing_rules,
)
from app.wishes import PLACEHOLDER_IMAGE, WISH_PRIZE_TAG


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

WISH_ACCEPTED_EVENT = "wish_accepted"

BACKFILL_SQL = sa.text(
    """
    INSERT INTO prizes
        (name, image, jd_url, real_value, purchase_value, redeem_value,
         stock, description, tag, is_active, origin_redemption_id)
    SELECT
        LEFT(CONCAT(r.custom_name, '（', COALESCE(w.name, ''), '）'), 200),
        :placeholder_image,
        r.custom_url,
        COALESCE(r.custom_price, 0),
        0,
        1,
        0,
        CONCAT(
            '心愿奖品，来源兑换单 ', r.order_no,
            CASE WHEN w.name IS NOT NULL AND w.name <> ''
                 THEN CONCAT('；获奖人 ', w.name) ELSE '' END,
            CASE WHEN r.custom_note IS NOT NULL AND r.custom_note <> ''
                 THEN CONCAT('；备注：', r.custom_note) ELSE '' END
        ),
        :wish_tag,
        0,
        r.id
    FROM redemptions r
    LEFT JOIN redemption_codes c ON c.id = r.code_id
    LEFT JOIN winners w ON w.id = c.winner_id
    WHERE r.custom_name IS NOT NULL
      AND NOT EXISTS (SELECT 1 FROM prizes p WHERE p.origin_redemption_id = r.id)
    """
)


def upgrade() -> None:
    connection = op.get_bind()
    # 1. New redemption status: an accepted wish waits in procuring (待备货)
    #    until the admin finishes stocking, instead of jumping to ready.
    connection.execute(
        sa.text(
            "ALTER TABLE redemptions MODIFY COLUMN status "
            "ENUM('submitted','procuring','ready','picked_up','cancelled') NOT NULL"
        )
    )
    # 2. Link auto-generated wish prizes back to their redemption.
    op.add_column("prizes", sa.Column("origin_redemption_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_prizes_origin_redemption",
        "prizes",
        "redemptions",
        ["origin_redemption_id"],
        ["id"],
    )
    # MySQL unique constraints allow multiple NULLs, so catalog prizes are unaffected.
    op.create_unique_constraint("uq_prizes_origin_redemption", "prizes", ["origin_redemption_id"])
    # 3. Backfill: every historical wish (including cancelled ones) gets a Prize
    #    row so procurement/reimbursement orders can reference it.
    connection.execute(
        BACKFILL_SQL,
        {"placeholder_image": PLACEHOLDER_IMAGE, "wish_tag": WISH_PRIZE_TAG},
    )
    # 4. wish_accepted notification templates and routing rules.
    connection.execute(
        sa.text(
            "INSERT IGNORE INTO notification_templates (event_type, text_template, html_template, updated_at) "
            "VALUES (:event_type, :text_template, :html_template, CURRENT_TIMESTAMP)"
        ),
        {
            "event_type": WISH_ACCEPTED_EVENT,
            "text_template": DEFAULT_TEMPLATES[WISH_ACCEPTED_EVENT],
            "html_template": DEFAULT_HTML_TEMPLATES[WISH_ACCEPTED_EVENT],
        },
    )
    for event_type, channel, recipient in default_routing_rules():
        if event_type != WISH_ACCEPTED_EVENT:
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
    # Destructive: wish-generated prizes and their purchase order items are
    # deleted. Development environments only.
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM purchase_order_items WHERE prize_id IN "
            "(SELECT id FROM (SELECT id FROM prizes WHERE origin_redemption_id IS NOT NULL) AS t)"
        )
    )
    connection.execute(sa.text("DELETE FROM prizes WHERE origin_redemption_id IS NOT NULL"))
    op.drop_constraint("uq_prizes_origin_redemption", "prizes", type_="unique")
    op.drop_constraint("fk_prizes_origin_redemption", "prizes", type_="foreignkey")
    op.drop_column("prizes", "origin_redemption_id")
    # Settle any wishes still mid-procuring before narrowing the enum.
    connection.execute(
        sa.text("UPDATE redemptions SET status = 'ready' WHERE status = 'procuring'")
    )
    connection.execute(
        sa.text(
            "ALTER TABLE redemptions MODIFY COLUMN status "
            "ENUM('submitted','ready','picked_up','cancelled') NOT NULL"
        )
    )
    connection.execute(
        sa.text("DELETE FROM notification_routing_rules WHERE event_type = :event_type"),
        {"event_type": WISH_ACCEPTED_EVENT},
    )
    connection.execute(
        sa.text("DELETE FROM notification_templates WHERE event_type = :event_type"),
        {"event_type": WISH_ACCEPTED_EVENT},
    )
