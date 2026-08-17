from datetime import datetime, timezone
from html import escape
import re
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    NotificationChannel,
    NotificationJob,
    NotificationRecipient,
    NotificationRoutingRule,
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
    "wish_submitted",
    "wish_rejected",
)

DEFAULT_RECIPIENTS = {
    "code_issued": NotificationRecipient.WINNER,
    "redemption_submitted": NotificationRecipient.OPERATIONS,
    "redemption_ready": NotificationRecipient.WINNER,
    "redemption_picked_up": NotificationRecipient.OPERATIONS,
    "redemption_cancelled": NotificationRecipient.WINNER,
    "wish_submitted": NotificationRecipient.OPERATIONS,
    "wish_rejected": NotificationRecipient.WINNER,
}


def default_routing_rules() -> list[tuple[str, NotificationChannel, NotificationRecipient]]:
    rules = []
    for event_type, recipient in DEFAULT_RECIPIENTS.items():
        rules.extend(
            [
                (event_type, NotificationChannel.EMAIL, recipient),
                (event_type, NotificationChannel.EMAIL_POSTER, recipient),
                (event_type, NotificationChannel.WEBHOOK, NotificationRecipient.WEBHOOK),
            ]
        )
    return rules

DEFAULT_TEMPLATES = {
    "code_issued": "{{winner_name}}，恭喜你在 {{event_name}} 中获得 {{award_name}}。你的兑换码是 {{code}}，可用额度为 {{quota}}。请于 {{deadline}} 前访问 {{redemption_url}} 完成兑换。自提地点：{{pickup_location}}。{{pickup_instructions}}",
    "redemption_submitted": "{{winner_name}} 已提交兑换单 {{order_no}}：{{items_summary}}。总抵扣 {{total_redeem_value}}，未使用额度 {{unused_quota}}，状态：{{status}}。",
    "redemption_ready": "{{winner_name}}，兑换单 {{order_no}} 已备货，请前往 {{pickup_location}} 领取。{{pickup_instructions}}",
    "redemption_picked_up": "兑换单 {{order_no}} 已领取。获奖人：{{winner_name}}；奖品：{{items_summary}}；状态：{{status}}。",
    "redemption_cancelled": "{{winner_name}}，兑换单 {{order_no}} 已取消，兑换码 {{code}} 已恢复使用。状态：{{status}}。",
    "wish_submitted": "{{winner_name}} 在 {{event_name}} 提交了自定义奖品申请 {{order_no}}：{{wish_name}}，期望价格 {{wish_price}}。链接：{{wish_url}}；备注：{{wish_note}}。请联系人 {{contact_name}} {{contact_phone}}。请在后台确认采纳或拒绝。",
    "wish_rejected": "{{winner_name}}，你提交的自定义奖品申请 {{wish_name}} 因为 {{reason}} 原因被驳回。兑换码 {{code}} 已恢复使用，可重新选择奖品。",
}


def html_document(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title}</title></head>
<body style="margin:0;background:#f1f5f9;font-family:Arial,'PingFang SC','Microsoft YaHei',sans-serif;color:#0f172a">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:32px 16px"><tr><td align="center">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#ffffff;border-radius:16px;overflow:hidden">
      <tr><td style="padding:28px 32px;background:#2563eb;color:#ffffff;font-size:22px;font-weight:700">PrizePass</td></tr>
      <tr><td style="padding:32px;font-size:16px;line-height:1.75"><h1 style="margin:0 0 20px;font-size:24px">{title}</h1>{body}</td></tr>
    </table>
  </td></tr></table>
</body>
</html>"""


DEFAULT_HTML_TEMPLATES = {
    "code_issued": html_document(
        "兑换码通知",
        "<p>{{winner_name}}，恭喜你在 <strong>{{event_name}}</strong> 中获得 <strong>{{award_name}}</strong>，奖品兑换资格已开通。</p>"
        "<p>兑换码：<strong style=\"font-size:22px;color:#2563eb\">{{code}}</strong><br>"
        "可用额度：{{quota}}<br>截止时间：{{deadline}}</p>"
        "<p><a href=\"{{redemption_url}}\" style=\"display:inline-block;padding:12px 20px;background:#2563eb;color:#fff;text-decoration:none;border-radius:8px\">前往兑换</a></p>"
        "<p>自提地点：{{pickup_location}}<br>{{pickup_instructions}}</p>",
    ),
    "redemption_submitted": html_document(
        "兑换已提交",
        "<p>{{winner_name}} 已提交兑换单 <strong>{{order_no}}</strong>。</p>"
        "<p>奖品：{{items_summary}}<br>总抵扣：{{total_redeem_value}}<br>未使用额度：{{unused_quota}}<br>状态：{{status}}</p>",
    ),
    "redemption_ready": html_document(
        "奖品待领取",
        "<p>{{winner_name}}，兑换单 <strong>{{order_no}}</strong> 已备货。</p>"
        "<p>请前往 {{pickup_location}} 领取。<br>{{pickup_instructions}}</p>",
    ),
    "redemption_picked_up": html_document(
        "兑换已领取",
        "<p>兑换单 <strong>{{order_no}}</strong> 已领取。</p>"
        "<p>获奖人：{{winner_name}}<br>奖品：{{items_summary}}<br>状态：{{status}}</p>",
    ),
    "redemption_cancelled": html_document(
        "兑换已取消",
        "<p>{{winner_name}}，兑换单 <strong>{{order_no}}</strong> 已取消。</p>"
        "<p>兑换码 <strong>{{code}}</strong> 已恢复使用。状态：{{status}}</p>",
    ),
    "wish_submitted": html_document(
        "新的自定义奖品申请",
        "<p>{{winner_name}} 在 <strong>{{event_name}}</strong> 提交了自定义奖品申请 <strong>{{order_no}}</strong>。</p>"
        "<p>奖品：{{wish_name}}<br>期望价格：{{wish_price}}<br>链接：<a href=\"{{wish_url}}\">{{wish_url}}</a><br>备注：{{wish_note}}</p>"
        "<p>联系人：{{contact_name}} {{contact_phone}}</p>"
        "<p>请在后台确认采纳（标记待领取）或拒绝（取消并恢复兑换码）。</p>",
    ),
    "wish_rejected": html_document(
        "自定义奖品申请被驳回",
        "<p>{{winner_name}}，你提交的自定义奖品申请 <strong>{{wish_name}}</strong> 因为 <strong>{{reason}}</strong> 原因被驳回。</p>"
        "<p>兑换码 <strong>{{code}}</strong> 已恢复使用，可重新选择奖品。</p>",
    ),
}

ALL_TEMPLATE_VARIABLES = {
    "winner_name",
    "winner_email",
    "event_name",
    "award_name",
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
    "wish_name",
    "wish_url",
    "wish_note",
    "wish_price",
    "reason",
    "contact_name",
    "contact_phone",
}
EVENT_VARIABLES = {
    "code_issued": {
        "winner_name",
        "winner_email",
        "event_name",
        "award_name",
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
    "wish_submitted": {
        "winner_name",
        "event_name",
        "order_no",
        "wish_name",
        "wish_url",
        "wish_note",
        "wish_price",
        "contact_name",
        "contact_phone",
    },
    "wish_rejected": {
        "winner_name",
        "event_name",
        "order_no",
        "wish_name",
        "wish_url",
        "wish_note",
        "wish_price",
        "reason",
        "code",
        "status",
    },
}
VARIABLE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def render_template(template: str, context: dict[str, str | int]) -> str:
    return VARIABLE_RE.sub(lambda match: str(context.get(match.group(1), match.group(0))), template)


def render_html_template(template: str | None, context: dict[str, str | int]) -> str | None:
    if template is None:
        return None
    return VARIABLE_RE.sub(
        lambda match: escape(str(context.get(match.group(1), match.group(0))), quote=True),
        template,
    )


def validate_template(event_type: str, template: str) -> set[str]:
    if event_type not in EVENT_VARIABLES:
        raise ValueError("未知通知事件类型")
    variables = set(VARIABLE_RE.findall(template))
    unknown = variables - EVENT_VARIABLES[event_type]
    remainder = VARIABLE_RE.sub("", template)
    if "{{" in remainder or "}}" in remainder:
        unknown.add("格式错误的变量")
    return unknown


def template_content(db: Session, event_type: str) -> tuple[str, str | None]:
    template = db.scalar(
        select(NotificationTemplate).where(NotificationTemplate.event_type == event_type)
    )
    if template is None:
        return DEFAULT_TEMPLATES[event_type], DEFAULT_HTML_TEMPLATES[event_type]
    return template.text_template, template.html_template


def template_text(db: Session, event_type: str) -> str:
    return template_content(db, event_type)[0]


def render_notification(
    db: Session, event_type: str, context: dict[str, str | int]
) -> tuple[str, str | None]:
    text_template, html_template = template_content(db, event_type)
    return render_template(text_template, context), render_html_template(html_template, context)


def code_issued_context(winner: Winner, code: str, event) -> dict[str, str | int]:
    settings = get_settings()
    # getattr keeps tests and ad-hoc callers working when the winner is a
    # SimpleNamespace without the new award_name attribute.
    award_name = getattr(winner, "award_name", None) or "奖项"
    return {
        "winner_name": winner.name,
        "winner_email": winner.email,
        "event_name": event.name,
        "award_name": award_name,
        "code": code,
        "quota": winner.quota,
        "redemption_url": f"{settings.public_base_url.rstrip('/')}/redeem?{urlencode({'code': code})}",
        "deadline": event.redemption_deadline.isoformat(sep=" "),
        "pickup_location": event.pickup_location,
        "pickup_instructions": event.pickup_instructions,
    }


def wish_submitted_context(
    winner: Winner, event, order_no: str, redemption
) -> dict[str, str | int]:
    return {
        "winner_name": winner.name,
        "event_name": event.name,
        "order_no": order_no,
        "wish_name": redemption.custom_name or "",
        "wish_url": redemption.custom_url or "无",
        "wish_note": redemption.custom_note or "无",
        "wish_price": f"{redemption.custom_price / 100:.2f} 元" if redemption.custom_price is not None else "未填写",
        "contact_name": redemption.contact_name,
        "contact_phone": redemption.contact_phone,
    }


def wish_rejected_context(
    winner: Winner, event, code: str, redemption, reason: str
) -> dict[str, str | int]:
    return {
        "winner_name": winner.name,
        "event_name": event.name,
        "order_no": redemption.order_no,
        "wish_name": redemption.custom_name or "",
        "wish_url": redemption.custom_url or "无",
        "wish_note": redemption.custom_note or "无",
        "wish_price": f"{redemption.custom_price / 100:.2f} 元" if redemption.custom_price is not None else "未填写",
        "reason": reason,
        "code": code,
        "status": redemption.status.value,
    }


def create_notification_jobs(
    db: Session,
    *,
    event_type: str,
    text_rendered: str,
    winner_email: str,
    html_rendered: str | None = None,
    winner_id: int | None = None,
    redemption_id: int | None = None,
) -> list[NotificationJob]:
    settings = get_settings()
    rules = list(
        db.scalars(
            select(NotificationRoutingRule)
            .where(NotificationRoutingRule.event_type == event_type)
            .order_by(NotificationRoutingRule.id)
        ).all()
    )

    jobs = []
    for rule in rules:
        if rule.channel is NotificationChannel.EMAIL_POSTER and not settings.email_poster_post_url:
            continue
        if rule.recipient is NotificationRecipient.WINNER:
            destination = winner_email
        elif rule.recipient is NotificationRecipient.OPERATIONS:
            destination = settings.notification_email
        else:
            destination = settings.webhook_url
        jobs.append(
            NotificationJob(
                event_type=event_type,
                channel=rule.channel,
                winner_id=winner_id,
                redemption_id=redemption_id,
                destination=destination,
                text_rendered=text_rendered,
                html_rendered=html_rendered,
                status=NotificationStatus.PENDING,
            )
        )
    db.add_all(jobs)
    return jobs


# Backward-compatible import for integrations that used the old helper name.
create_notification_pair = create_notification_jobs
