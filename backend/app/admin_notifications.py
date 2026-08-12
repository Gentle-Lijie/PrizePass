from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlsplit

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_admin_password
from .config import get_settings
from .database import get_db
from .http import fail
from .models import (
    NotificationChannel,
    NotificationJob,
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


class EmailTestRequest(StrictModel):
    email: str

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        try:
            return validate_email(value.strip().lower(), check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            raise ValueError("邮箱格式不合法") from exc


def serialize_template(template: NotificationTemplate) -> dict:
    return {
        "event_type": template.event_type,
        "text_template": template.text_template,
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
        "configuration": {
            "smtp": bool(settings.smtp_host and settings.smtp_from_email),
            "notification_email": bool(settings.notification_email),
            "webhook": bool(settings.webhook_url),
        },
    }


@router.put("/notification-templates/{event_type}")
def update_template(event_type: str, payload: TemplateUpdate, db: DbSession) -> dict:
    if event_type not in EVENT_TYPES:
        fail(404, "template_not_found", "通知模板不存在")
    unknown = validate_template(event_type, payload.text_template)
    if unknown:
        fail(422, "unknown_template_variable", "模板包含当前事件不可用的变量", {"variables": sorted(unknown)})
    template = db.scalar(
        select(NotificationTemplate).where(NotificationTemplate.event_type == event_type)
    )
    if template is None:
        fail(404, "template_not_found", "通知模板不存在")
    template.text_template = payload.text_template
    template.updated_at = utc_now()
    db.commit()
    db.refresh(template)
    return serialize_template(template)


def mask_destination(job: NotificationJob) -> str:
    if job.channel is NotificationChannel.EMAIL:
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
