from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends
from pydantic import Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import require_admin_password
from .config import get_settings
from .database import get_db
from .http import fail
from .models import (
    NotificationChannel,
    NotificationJob,
    NotificationRecipient,
    NotificationRoutingRule,
    NotificationStatus,
    NotificationTemplate,
)
from .notifications import EVENT_TYPES, EVENT_VARIABLES, utc_now, validate_template
from .schemas import StrictModel
from .timeutils import utc_iso


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin_password)],
    tags=["admin-notifications"],
)
DbSession = Annotated[Session, Depends(get_db)]


class TemplateUpdate(StrictModel):
    text_template: Annotated[str, Field(min_length=1, max_length=20_000)]
    html_template: Annotated[str | None, Field(max_length=50_000)] = None


class EmailTestRequest(StrictModel):
    email: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        try:
            return validate_email(value.strip().lower(), check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            raise ValueError("邮箱格式不合法") from exc


class RoutingConfig(StrictModel):
    event_type: str
    smtp_winner: bool = False
    smtp_operations: bool = False
    email_poster_winner: bool = False
    email_poster_operations: bool = False
    webhook: bool = False


class RoutingUpdate(StrictModel):
    routes: Annotated[list[RoutingConfig], Field(min_length=5, max_length=5)]


def serialize_routing(db: Session) -> list[dict]:
    result = {
        event_type: RoutingConfig(event_type=event_type).model_dump()
        for event_type in EVENT_TYPES
    }
    rules = db.scalars(select(NotificationRoutingRule).order_by(NotificationRoutingRule.id)).all()
    for rule in rules:
        route = result.get(rule.event_type)
        if route is None:
            continue
        if rule.channel is NotificationChannel.EMAIL:
            route[f"smtp_{rule.recipient.value}"] = True
        elif rule.channel is NotificationChannel.EMAIL_POSTER:
            route[f"email_poster_{rule.recipient.value}"] = True
        elif rule.recipient is NotificationRecipient.WEBHOOK:
            route["webhook"] = True
    return list(result.values())


def serialize_template(template: NotificationTemplate) -> dict:
    return {
        "event_type": template.event_type,
        "text_template": template.text_template,
        "html_template": template.html_template,
        "allowed_variables": sorted(EVENT_VARIABLES[template.event_type]),
        "updated_at": utc_iso(template.updated_at),
    }


@router.get("/notification-templates")
def list_templates(db: DbSession) -> dict:
    templates = db.scalars(
        select(NotificationTemplate).order_by(NotificationTemplate.id)
    ).all()
    settings = get_settings()
    return {
        "templates": [serialize_template(template) for template in templates],
        "routing": serialize_routing(db),
        "configuration": {
            "smtp": bool(settings.smtp_host and settings.smtp_from_email),
            "notification_email": bool(settings.notification_email),
            "webhook": bool(settings.webhook_url),
            "email_poster": bool(settings.email_poster_post_url),
        },
    }


@router.put("/notification-routing")
def update_routing(payload: RoutingUpdate, db: DbSession) -> dict:
    event_types = [route.event_type for route in payload.routes]
    if set(event_types) != set(EVENT_TYPES) or len(set(event_types)) != len(EVENT_TYPES):
        fail(422, "invalid_notification_routing", "必须且只能配置全部通知场景")

    rules = []
    for route in payload.routes:
        selections = (
            (route.smtp_winner, NotificationChannel.EMAIL, NotificationRecipient.WINNER),
            (route.smtp_operations, NotificationChannel.EMAIL, NotificationRecipient.OPERATIONS),
            (
                route.email_poster_winner,
                NotificationChannel.EMAIL_POSTER,
                NotificationRecipient.WINNER,
            ),
            (
                route.email_poster_operations,
                NotificationChannel.EMAIL_POSTER,
                NotificationRecipient.OPERATIONS,
            ),
            (route.webhook, NotificationChannel.WEBHOOK, NotificationRecipient.WEBHOOK),
        )
        rules.extend(
            NotificationRoutingRule(
                event_type=route.event_type,
                channel=channel,
                recipient=recipient,
            )
            for enabled, channel, recipient in selections
            if enabled
        )
    db.execute(delete(NotificationRoutingRule))
    db.add_all(rules)
    db.commit()
    return {"routing": serialize_routing(db)}


@router.put("/notification-templates/{event_type}")
def update_template(event_type: str, payload: TemplateUpdate, db: DbSession) -> dict:
    if event_type not in EVENT_TYPES:
        fail(404, "template_not_found", "通知模板不存在")
    unknown = validate_template(event_type, payload.text_template)
    template = db.scalar(
        select(NotificationTemplate).where(NotificationTemplate.event_type == event_type)
    )
    if template is None:
        fail(404, "template_not_found", "通知模板不存在")
    html_template = template.html_template
    if "html_template" in payload.model_fields_set:
        html_template = (payload.html_template or "").strip() or None
    if html_template:
        unknown.update(validate_template(event_type, html_template))
    if unknown:
        fail(422, "unknown_template_variable", "模板包含当前事件不可用的变量", {"variables": sorted(unknown)})
    template.text_template = payload.text_template
    template.html_template = html_template
    template.updated_at = utc_now()
    db.commit()
    db.refresh(template)
    return serialize_template(template)


def mask_destination(job: NotificationJob) -> str:
    if job.channel in (NotificationChannel.EMAIL, NotificationChannel.EMAIL_POSTER):
        local, separator, domain = job.destination.partition("@")
        if not separator:
            return "未配置"
        return f"{local[:1]}***@{domain}"
    parsed = urlsplit(job.destination)
    return f"{parsed.scheme}://{parsed.netloc}/…" if parsed.scheme and parsed.netloc else "未配置"


def serialize_job(job: NotificationJob) -> dict:
    return {
        "id": job.id,
        "event_type": job.event_type,
        "channel": job.channel.value,
        "destination": mask_destination(job),
        "text_rendered": job.text_rendered,
        "html_rendered": job.html_rendered,
        "status": job.status.value,
        "attempt_count": job.attempt_count,
        "next_attempt_at": utc_iso(job.next_attempt_at),
        "last_error": job.last_error,
        "sent_at": utc_iso(job.sent_at),
        "created_at": utc_iso(job.created_at),
    }


@router.get("/notification-jobs")
def list_jobs(db: DbSession) -> list[dict]:
    jobs = db.scalars(
        select(NotificationJob)
        .order_by(NotificationJob.created_at.desc(), NotificationJob.id.desc())
        .limit(100)
    ).all()
    return [serialize_job(job) for job in jobs]


@router.post("/notification-jobs/{job_id}/retry")
def retry_job(job_id: int, db: DbSession) -> dict:
    job = db.scalar(
        select(NotificationJob).where(NotificationJob.id == job_id).with_for_update()
    )
    if job is None:
        fail(404, "notification_job_not_found", "通知任务不存在")
    if job.status is not NotificationStatus.FAILED:
        fail(409, "notification_job_not_failed", "只有失败任务可以手工重试")
    job.status = NotificationStatus.PENDING
    job.next_attempt_at = None
    db.commit()
    db.refresh(job)
    return serialize_job(job)


@router.post("/notifications/test-email", status_code=201)
def test_email(payload: EmailTestRequest, db: DbSession) -> dict:
    job = NotificationJob(
        event_type="code_issued",
        channel=NotificationChannel.EMAIL,
        destination=payload.email,
        text_rendered="PrizePass Email 测试通知",
        html_rendered="<p><strong>PrizePass</strong> Email 测试通知</p>",
        status=NotificationStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return serialize_job(job)


@router.post("/notifications/test-email-poster", status_code=201)
def test_email_poster(payload: EmailTestRequest, db: DbSession) -> dict:
    if not get_settings().email_poster_post_url:
        fail(409, "email_poster_not_configured", "EMAIL_POSTER_POST_URL 尚未配置")
    job = NotificationJob(
        event_type="code_issued",
        channel=NotificationChannel.EMAIL_POSTER,
        destination=payload.email,
        text_rendered="PrizePass email-poster 测试通知",
        html_rendered="<p><strong>PrizePass</strong> email-poster 测试通知</p>",
        status=NotificationStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return serialize_job(job)


@router.post("/notifications/test-webhook", status_code=201)
def test_webhook(db: DbSession) -> dict:
    destination = get_settings().webhook_url
    if not destination:
        fail(409, "webhook_not_configured", "WEBHOOK_URL 尚未配置")
    job = NotificationJob(
        event_type="code_issued",
        channel=NotificationChannel.WEBHOOK,
        destination=destination,
        text_rendered="PrizePass Webhook 测试通知",
        status=NotificationStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return serialize_job(job)
