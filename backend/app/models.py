from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    func,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class EventStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class CodeStatus(StrEnum):
    ISSUED = "issued"
    REDEEMED = "redeemed"
    DISABLED = "disabled"


class RedemptionStatus(StrEnum):
    SUBMITTED = "submitted"
    READY = "ready"
    PICKED_UP = "picked_up"
    CANCELLED = "cancelled"


class NotificationChannel(StrEnum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    EMAIL_POSTER = "email_poster"


class NotificationRecipient(StrEnum):
    WINNER = "winner"
    OPERATIONS = "operations"
    WEBHOOK = "webhook"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    RETRYING = "retrying"
    SENT = "sent"
    FAILED = "failed"


def enum_type(enum: type[StrEnum], name: str) -> Enum:
    return Enum(enum, values_callable=lambda values: [item.value for item in values], name=name)


created_at = lambda: mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
updated_at = lambda: mapped_column(
    DateTime,
    nullable=False,
    server_default=text("CURRENT_TIMESTAMP"),
    server_onupdate=text("CURRENT_TIMESTAMP"),
    onupdate=func.current_timestamp(),
)
uint = lambda: mapped_column(INTEGER(unsigned=True), nullable=False)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[EventStatus] = mapped_column(enum_type(EventStatus, "event_status"), nullable=False)
    redemption_deadline: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    pickup_location: Mapped[str] = mapped_column(Text, nullable=False)
    pickup_instructions: Mapped[str] = mapped_column(Text, nullable=False)
    budget: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Prize(Base):
    __tablename__ = "prizes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    image: Mapped[str] = mapped_column(Text, nullable=False)
    jd_url: Mapped[str | None] = mapped_column(Text)
    real_value: Mapped[int] = uint()
    purchase_value: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    redeem_value: Mapped[int] = uint()
    # Signed so accepted redemptions can create a back-order when demand exceeds stock.
    stock: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Free-text label used to group prizes into collapsible sections on the redemption page.
    tag: Mapped[str | None] = mapped_column(String(100))
    # Off-shelf prizes stay visible to admins but are hidden from the redemption page.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Winner(Base):
    __tablename__ = "winners"
    __table_args__ = (UniqueConstraint("event_id", "identity_key", name="uq_winner_event_identity"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id"), nullable=False, index=True)
    external_id: Mapped[str | None] = mapped_column(String(200))
    identity_key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    quota: Mapped[int] = uint()
    created_at: Mapped[datetime] = created_at()


class RedemptionCode(Base):
    __tablename__ = "redemption_codes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id"), nullable=False, index=True)
    winner_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("winners.id"), nullable=False, unique=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    quota: Mapped[int] = uint()
    status: Mapped[CodeStatus] = mapped_column(enum_type(CodeStatus, "code_status"), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class Redemption(Base):
    __tablename__ = "redemptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    event_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("events.id"), nullable=False, index=True)
    code_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("redemption_codes.id"), nullable=False, unique=True)
    contact_name: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(30), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    # A winner may describe a custom desired prize instead of picking catalog
    # items; such redemptions have no items and skip quota math.
    custom_name: Mapped[str | None] = mapped_column(String(200))
    custom_url: Mapped[str | None] = mapped_column(Text)
    custom_note: Mapped[str | None] = mapped_column(Text)
    custom_price: Mapped[int | None] = mapped_column(INTEGER(unsigned=True))
    total_redeem_value: Mapped[int] = uint()
    quota_snapshot: Mapped[int] = uint()
    pickup_location_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    pickup_instructions_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RedemptionStatus] = mapped_column(
        enum_type(RedemptionStatus, "redemption_status"), nullable=False
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)


class RedemptionItem(Base):
    __tablename__ = "redemption_items"
    __table_args__ = (UniqueConstraint("redemption_id", "prize_id", name="uq_redemption_prize"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    redemption_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("redemptions.id"), nullable=False, index=True)
    prize_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("prizes.id"), nullable=False, index=True)
    prize_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    prize_image_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    real_value_snapshot: Mapped[int] = uint()
    purchase_value_snapshot: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    redeem_value_snapshot: Mapped[int] = uint()
    quantity: Mapped[int] = uint()
    line_redeem_value: Mapped[int] = uint()


class NotificationTemplate(Base):
    __tablename__ = "notification_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    text_template: Mapped[str] = mapped_column(Text, nullable=False)
    html_template: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = updated_at()


class NotificationRoutingRule(Base):
    __tablename__ = "notification_routing_rules"
    __table_args__ = (
        UniqueConstraint(
            "event_type", "channel", "recipient", name="uq_notification_routing_rule"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_type(NotificationChannel, "notification_routing_channel"), nullable=False
    )
    recipient: Mapped[NotificationRecipient] = mapped_column(
        enum_type(NotificationRecipient, "notification_recipient"), nullable=False
    )
    updated_at: Mapped[datetime] = updated_at()


class NotificationJob(Base):
    __tablename__ = "notification_jobs"
    __table_args__ = (Index("ix_notification_jobs_claim", "status", "next_attempt_at", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_type(NotificationChannel, "notification_channel"), nullable=False
    )
    winner_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("winners.id"))
    redemption_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("redemptions.id"))
    destination: Mapped[str] = mapped_column(Text, nullable=False)
    text_rendered: Mapped[str] = mapped_column(Text, nullable=False)
    html_rendered: Mapped[str | None] = mapped_column(Text)
    status: Mapped[NotificationStatus] = mapped_column(
        enum_type(NotificationStatus, "notification_status"), nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(INTEGER(unsigned=True), nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
