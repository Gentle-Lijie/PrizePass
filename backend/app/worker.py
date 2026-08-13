import logging
import smtplib
import time
from datetime import timedelta
from email.message import EmailMessage

import httpx
from sqlalchemy import or_, select, update

from .config import get_settings
from .database import SessionLocal
from .models import NotificationChannel, NotificationJob, NotificationStatus
from .notifications import utc_now
from .timeutils import utc_iso


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("prizepass.worker")
SUBJECTS = {
    "code_issued": "[PrizePass] 兑换码通知",
    "redemption_submitted": "[PrizePass] 兑换已提交",
    "redemption_ready": "[PrizePass] 奖品待领取",
    "redemption_picked_up": "[PrizePass] 兑换已领取",
    "redemption_cancelled": "[PrizePass] 兑换已取消",
}
EMAIL_POSTER_PRESETS = {
    "none": {},
    "smtogo": {"from": "from", "to": "to", "subject": "subject", "bodyHtml": "html"},
    "generic": {
        "from": "from",
        "to": "to",
        "subject": "subject",
        "bodyHtml": "html",
        "bodyText": "text",
    },
    "custom_example": {"to": "email", "subject": "subject", "body": "content"},
}


def send_email(job: NotificationJob) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from_email:
        raise RuntimeError("SMTP 未完整配置")
    message = EmailMessage()
    message["Subject"] = SUBJECTS[job.event_type]
    message["From"] = (
        f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        if settings.smtp_from_name
        else settings.smtp_from_email
    )
    message["To"] = job.destination
    message.set_content(job.text_rendered)
    if job.html_rendered:
        message.add_alternative(job.html_rendered, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)


def send_webhook(job: NotificationJob) -> None:
    if not job.destination:
        raise RuntimeError("WEBHOOK_URL 未配置")
    response = httpx.post(
        job.destination,
        json={
            "event_type": job.event_type,
            "text": job.text_rendered,
            "html": job.html_rendered,
            "occurred_at": utc_iso(job.created_at),
        },
        timeout=20,
    )
    response.raise_for_status()


def build_email_poster_payload(job: NotificationJob) -> dict[str, object]:
    """Build the same logical payload as email-poster's field-map presets."""
    settings = get_settings()
    if settings.email_poster_preset not in EMAIL_POSTER_PRESETS:
        raise RuntimeError(f"不支持的 EMAIL_POSTER_PRESET: {settings.email_poster_preset}")
    fields = {
        **EMAIL_POSTER_PRESETS[settings.email_poster_preset],
        **settings.email_poster_fields,
    }
    payload: dict[str, object] = dict(settings.email_poster_extra)
    if fields.get("from") and settings.email_poster_from_address:
        payload[fields["from"]] = settings.email_poster_from_address
    if not fields.get("to") or not fields.get("subject"):
        raise RuntimeError("email-poster 字段映射必须包含 to 和 subject")
    payload[fields["to"]] = job.destination
    payload[fields["subject"]] = SUBJECTS[job.event_type]

    body_type = "html" if job.html_rendered else "text"
    body = job.html_rendered or job.text_rendered
    if fields.get("body"):
        payload[fields["body"]] = body
    else:
        body_field = fields.get("bodyHtml" if body_type == "html" else "bodyText")
        if not body_field:
            raise RuntimeError(f"email-poster 字段映射缺少 {body_type} 正文字段")
        payload[body_field] = body
    if fields.get("type"):
        payload[fields["type"]] = body_type
    return payload


def send_email_poster(job: NotificationJob) -> None:
    settings = get_settings()
    if not settings.email_poster_post_url:
        raise RuntimeError("EMAIL_POSTER_POST_URL 未配置")
    headers = {**settings.email_poster_headers, "Content-Type": "application/json"}
    response = httpx.post(
        settings.email_poster_post_url,
        json=build_email_poster_payload(job),
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()


def recover_stale_jobs() -> int:
    cutoff = utc_now() - timedelta(minutes=10)
    with SessionLocal.begin() as db:
        result = db.execute(
            update(NotificationJob)
            .where(
                NotificationJob.status == NotificationStatus.SENDING,
                NotificationJob.updated_at < cutoff,
            )
            .values(status=NotificationStatus.PENDING, next_attempt_at=None, updated_at=utc_now())
        )
        return result.rowcount


def claim_jobs(limit: int = 10) -> list[int]:
    now = utc_now()
    with SessionLocal.begin() as db:
        jobs = list(
            db.scalars(
                select(NotificationJob)
                .where(
                    NotificationJob.status.in_(
                        [NotificationStatus.PENDING, NotificationStatus.RETRYING]
                    ),
                    or_(
                        NotificationJob.next_attempt_at.is_(None),
                        NotificationJob.next_attempt_at <= now,
                    ),
                )
                .order_by(NotificationJob.created_at, NotificationJob.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        for job in jobs:
            job.status = NotificationStatus.SENDING
            job.updated_at = now
        return [job.id for job in jobs]


def process_job(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(NotificationJob, job_id)
        if job is None or job.status is not NotificationStatus.SENDING:
            return
        try:
            if job.channel is NotificationChannel.EMAIL:
                send_email(job)
            elif job.channel is NotificationChannel.WEBHOOK:
                send_webhook(job)
            else:
                send_email_poster(job)
        except Exception as exc:
            job.attempt_count += 1
            job.last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
            if job.attempt_count == 1:
                job.status = NotificationStatus.RETRYING
                job.next_attempt_at = utc_now() + timedelta(minutes=1)
            elif job.attempt_count == 2:
                job.status = NotificationStatus.RETRYING
                job.next_attempt_at = utc_now() + timedelta(minutes=5)
            else:
                job.status = NotificationStatus.FAILED
                job.next_attempt_at = None
            logger.warning("Notification job %s failed on attempt %s", job.id, job.attempt_count)
        else:
            job.attempt_count += 1
            job.status = NotificationStatus.SENT
            job.sent_at = utc_now()
            job.next_attempt_at = None
            job.last_error = None
        job.updated_at = utc_now()
        db.commit()


def run_once() -> int:
    job_ids = claim_jobs()
    for job_id in job_ids:
        process_job(job_id)
    return len(job_ids)


def run() -> None:
    settings = get_settings()
    recovered = recover_stale_jobs()
    logger.info("PrizePass notification worker started; recovered %s stale jobs", recovered)
    while True:
        processed = run_once()
        if processed == 0:
            time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    run()
