from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import app
from app.models import NotificationChannel, NotificationJob, NotificationStatus
from app.notifications import utc_now
from app import worker
from tests.conftest import test_engine


client = TestClient(app)
ADMIN = {"X-Admin-Password": "prizepass-dev-admin"}


def create_job(channel: NotificationChannel = NotificationChannel.EMAIL) -> int:
    with Session(test_engine) as session:
        job = NotificationJob(
            event_type="code_issued",
            channel=channel,
            destination="recipient@example.com" if channel is NotificationChannel.EMAIL else "https://example.com/hook",
            text_rendered="测试文本",
            status=NotificationStatus.PENDING,
        )
        session.add(job)
        session.commit()
        return job.id


def test_templates_are_fixed_and_reject_unknown_variables() -> None:
    response = client.get("/api/admin/notification-templates", headers=ADMIN)
    assert response.status_code == 200
    assert len(response.json()["templates"]) == 5
    assert "smtp" in response.json()["configuration"]
    invalid = client.put(
        "/api/admin/notification-templates/code_issued",
        headers=ADMIN,
        json={"text_template": "你好 {{order_no}} {{unknown}}"},
    )
    assert invalid.status_code == 422
    assert set(invalid.json()["error"]["details"]["variables"]) == {"order_no", "unknown"}
    valid = client.put(
        "/api/admin/notification-templates/code_issued",
        headers=ADMIN,
        json={"text_template": "{{winner_name}} 的兑换码为 {{code}}"},
    )
    assert valid.status_code == 200


def test_email_test_creates_regular_pending_job_and_masks_target() -> None:
    created = client.post(
        "/api/admin/notifications/test-email",
        headers=ADMIN,
        json={"email": "Receiver@Example.com"},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    assert created.json()["destination"] == "r***@example.com"
    jobs = client.get("/api/admin/notification-jobs", headers=ADMIN)
    assert jobs.status_code == 200
    assert jobs.json()[0]["id"] == created.json()["id"]


def test_worker_retries_at_one_and_five_minutes_then_fails(monkeypatch) -> None:
    job_id = create_job()

    def always_fail(_job):
        raise RuntimeError("temporary failure")

    monkeypatch.setattr(worker, "send_email", always_fail)
    assert worker.claim_jobs(limit=1) == [job_id]
    worker.process_job(job_id)
    with Session(test_engine) as session:
        job = session.get(NotificationJob, job_id)
        assert job.status is NotificationStatus.RETRYING
        assert job.attempt_count == 1
        assert timedelta(seconds=50) < job.next_attempt_at - utc_now() <= timedelta(seconds=61)

    with Session(test_engine) as session:
        job = session.get(NotificationJob, job_id)
        job.status = NotificationStatus.SENDING
        session.commit()
    worker.process_job(job_id)
    with Session(test_engine) as session:
        job = session.get(NotificationJob, job_id)
        assert job.status is NotificationStatus.RETRYING
        assert job.attempt_count == 2
        assert timedelta(minutes=4, seconds=50) < job.next_attempt_at - utc_now() <= timedelta(minutes=5, seconds=1)

    with Session(test_engine) as session:
        job = session.get(NotificationJob, job_id)
        job.status = NotificationStatus.SENDING
        session.commit()
    worker.process_job(job_id)
    with Session(test_engine) as session:
        job = session.get(NotificationJob, job_id)
        assert job.status is NotificationStatus.FAILED
        assert job.attempt_count == 3
        assert job.next_attempt_at is None

    retried = client.post(f"/api/admin/notification-jobs/{job_id}/retry", headers=ADMIN)
    assert retried.status_code == 200
    assert retried.json()["status"] == "pending"
    assert retried.json()["next_attempt_at"] is None


def test_channel_failure_does_not_affect_other_channel(monkeypatch) -> None:
    email_id = create_job(NotificationChannel.EMAIL)
    webhook_id = create_job(NotificationChannel.WEBHOOK)
    with Session(test_engine) as session:
        session.execute(
            update(NotificationJob)
            .where(NotificationJob.id.in_([email_id, webhook_id]))
            .values(status=NotificationStatus.SENDING)
        )
        session.commit()

    monkeypatch.setattr(worker, "send_email", lambda _job: (_ for _ in ()).throw(RuntimeError("smtp down")))
    monkeypatch.setattr(worker, "send_webhook", lambda _job: None)
    worker.process_job(email_id)
    worker.process_job(webhook_id)
    with Session(test_engine) as session:
        assert session.get(NotificationJob, email_id).status is NotificationStatus.RETRYING
        assert session.get(NotificationJob, webhook_id).status is NotificationStatus.SENT


def test_worker_recovers_stale_sending_jobs() -> None:
    job_id = create_job()
    with Session(test_engine) as session:
        session.execute(
            update(NotificationJob)
            .where(NotificationJob.id == job_id)
            .values(status=NotificationStatus.SENDING, updated_at=utc_now() - timedelta(minutes=11))
        )
        session.commit()
    assert worker.recover_stale_jobs() == 1
    with Session(test_engine) as session:
        assert session.get(NotificationJob, job_id).status is NotificationStatus.PENDING
