from datetime import datetime, timezone
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    NotificationChannel,
    NotificationJob,
    NotificationStatus,
    NotificationTemplate,
    Redemption,
    Winner,
)


EVENT_TYPES = (
    "code_issued",
    "redemption_submitted",
    "redemption_ready",
    "redemption_picked_up",
    "redemption_cancelled",
)

DEFAULT_TEMPLATES = {
    "code_issued": "{{winner_name}}，你的兑换码是 {{code}}，可用额度为 {{quota}}。请于 {{deadline}} 前访问 {{redemption_url}} 完成兑换。自提地点：{{pickup_location}}。{{pickup_instructions}}",
    "redemption_submitted": "{{winner_name}} 已提交兑换单 {{order_no}}：{{items_summary}}。总抵扣 {{total_redeem_value}}，未使用额度 {{unused_quota}}，状态：{{status}}。",
    "redemption_ready": "{{winner_name}}，兑换单 {{order_no}} 已备货，请前往 {{pickup_location}} 领取。{{pickup_instructions}}",
    "redemption_picked_up": "兑换单 {{order_no}} 已领取。获奖人：{{winner_name}}；奖品：{{items_summary}}；状态：{{status}}。",
    "redemption_cancelled": "{{winner_name}}，兑换单 {{order_no}} 已取消，兑换码 {{code}} 已恢复使用。状态：{{status}}。",
}

ALL_TEMPLATE_VARIABLES = {
    "winner_name",
    "winner_email",
    "event_name",
    "code",
    "quota",
    "redemption_url",
    "deadline",
    "order_no",
    "items_summary",
    "total_redeem_value",
    "unused_quota",
    "status",
    "pickup_location",
    "pickup_instructions",
}
EVENT_VARIABLES = {
    "code_issued": {
        "winner_name",
        "winner_email",
        "event_name",
        "code",
        "quota",
        "redemption_url",
        "deadline",
        "pickup_location",
        "pickup_instructions",
    },
    "redemption_submitted": ALL_TEMPLATE_VARIABLES,
    "redemption_ready": ALL_TEMPLATE_VARIABLES,
    "redemption_picked_up": ALL_TEMPLATE_VARIABLES,
    "redemption_cancelled": ALL_TEMPLATE_VARIABLES,
}
VARIABLE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def render_template(template: str, context: dict[str, str | int]) -> str:
    return VARIABLE_RE.sub(lambda match: str(context.get(match.group(1), match.group(0))), template)


def validate_template(event_type: str, template: str) -> set[str]:
    if event_type not in EVENT_VARIABLES:
        raise ValueError("未知通知事件类型")
    variables = set(VARIABLE_RE.findall(template))
    unknown = variables - EVENT_VARIABLES[event_type]
    remainder = VARIABLE_RE.sub("", template)
    if "{{" in remainder or "}}" in remainder:
        unknown.add("格式错误的变量")
    return unknown


def template_text(db: Session, event_type: str) -> str:
    template = db.scalar(
        select(NotificationTemplate.text_template).where(NotificationTemplate.event_type == event_type)
    )
    return template or DEFAULT_TEMPLATES[event_type]


def code_issued_context(winner: Winner, code: str, event) -> dict[str, str | int]:
    settings = get_settings()
    return {
        "winner_name": winner.name,
        "winner_email": winner.email,
        "event_name": event.name,
        "code": code,
        "quota": winner.quota,
        "redemption_url": f"{settings.public_base_url.rstrip('/')}/redeem",
        "deadline": event.redemption_deadline.isoformat(sep=" "),
        "pickup_location": event.pickup_location,
        "pickup_instructions": event.pickup_instructions,
    }


def create_notification_pair(
    db: Session,
    *,
    event_type: str,
    text_rendered: str,
    email_destination: str,
    winner_id: int | None = None,
    redemption_id: int | None = None,
) -> list[NotificationJob]:
    settings = get_settings()
    jobs = [
        NotificationJob(
            event_type=event_type,
            channel=NotificationChannel.EMAIL,
            winner_id=winner_id,
            redemption_id=redemption_id,
            destination=email_destination,
            text_rendered=text_rendered,
            status=NotificationStatus.PENDING,
        ),
        NotificationJob(
            event_type=event_type,
            channel=NotificationChannel.WEBHOOK,
            winner_id=winner_id,
            redemption_id=redemption_id,
            destination=settings.webhook_url,
            text_rendered=text_rendered,
            status=NotificationStatus.PENDING,
        ),
    ]
    db.add_all(jobs)
    return jobs
