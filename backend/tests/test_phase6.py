from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import app
from app.models import (
    NotificationChannel,
    NotificationJob,
    NotificationStatus,
)
from app.notifications import create_notification_jobs, render_html_template, utc_now
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
    assert len(response.json()["templates"]) == 7
    assert "smtp" in response.json()["configuration"]
    assert "email_poster" in response.json()["configuration"]
    assert response.json()["templates"][0]["html_template"]
    assert len(response.json()["routing"]) == 7
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
        json={
            "text_template": "{{winner_name}} 的兑换码为 {{code}}",
            "html_template": "<p>{{winner_name}} 的兑换码为 <strong>{{code}}</strong></p>",
        },
    )
    assert valid.status_code == 200
    assert valid.json()["html_template"].startswith("<p>")

    invalid_html = client.put(
        "/api/admin/notification-templates/code_issued",
        headers=ADMIN,
        json={"text_template": "{{winner_name}}", "html_template": "<p>{{order_no}}</p>"},
    )
    assert invalid_html.status_code == 422


def test_html_template_escapes_context_values_and_can_be_disabled() -> None:
    assert render_html_template("<p>{{winner_name}}</p>", {"winner_name": '<Admin & "Co">'}) == (
        "<p>&lt;Admin &amp; &quot;Co&quot;&gt;</p>"
    )
    disabled = client.put(
        "/api/admin/notification-templates/code_issued",
        headers=ADMIN,
        json={"text_template": "纯文本 {{code}}", "html_template": "   "},
    )
    assert disabled.status_code == 200
    assert disabled.json()["html_template"] is None


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


def test_email_poster_payload_supports_html_and_plain_text(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "email_poster_preset", "generic")
    monkeypatch.setattr(settings, "email_poster_from_address", "sender@example.com")
    monkeypatch.setattr(settings, "email_poster_extra", {"source": "prizepass"})
    monkeypatch.setattr(settings, "email_poster_fields", {"type": "contentType"})

    html_job = NotificationJob(
        event_type="code_issued",
        channel=NotificationChannel.EMAIL_POSTER,
        destination="recipient@example.com",
        text_rendered="纯文本",
        html_rendered="<p>HTML</p>",
        status=NotificationStatus.PENDING,
    )
    assert worker.build_email_poster_payload(html_job) == {
        "source": "prizepass",
        "from": "sender@example.com",
        "to": "recipient@example.com",
        "subject": "[PrizePass] 兑换码通知",
        "html": "<p>HTML</p>",
        "contentType": "html",
    }

    html_job.html_rendered = None
    plain_payload = worker.build_email_poster_payload(html_job)
    assert plain_payload["text"] == "纯文本"
    assert plain_payload["contentType"] == "text"


def test_configured_email_poster_adds_an_independent_job(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "email_poster_post_url", "https://relay.example.com/send")
    with Session(test_engine) as session:
        jobs = create_notification_jobs(
            session,
            event_type="code_issued",
            text_rendered="纯文本",
            html_rendered="<p>HTML</p>",
            winner_email="recipient@example.com",
        )
        session.commit()
        assert {job.channel for job in jobs} == {
            NotificationChannel.EMAIL,
            NotificationChannel.WEBHOOK,
            NotificationChannel.EMAIL_POSTER,
        }
        poster_job = next(job for job in jobs if job.channel is NotificationChannel.EMAIL_POSTER)
        assert poster_job.destination == "recipient@example.com"
        assert poster_job.html_rendered == "<p>HTML</p>"


def test_email_poster_posts_json_with_configured_headers(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "email_poster_post_url", "https://relay.example.com/send")
    monkeypatch.setattr(settings, "email_poster_preset", "generic")
    monkeypatch.setattr(settings, "email_poster_headers", {"Authorization": "Bearer test"})
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(worker.httpx, "post", fake_post)
    job = NotificationJob(
        event_type="code_issued",
        channel=NotificationChannel.EMAIL_POSTER,
        destination="recipient@example.com",
        text_rendered="纯文本",
        html_rendered="<p>HTML</p>",
        status=NotificationStatus.PENDING,
    )
    worker.send_email_poster(job)
    assert captured["url"] == "https://relay.example.com/send"
    assert captured["json"]["html"] == "<p>HTML</p>"
    assert captured["headers"] == {
        "Authorization": "Bearer test",
        "Content-Type": "application/json",
    }


def test_routing_configuration_controls_channel_and_recipient(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_email", "operations@example.com")
    monkeypatch.setattr(settings, "email_poster_post_url", "https://relay.example.com/send")
    current = client.get("/api/admin/notification-templates", headers=ADMIN).json()["routing"]
    for route in current:
        route.update(
            smtp_winner=False,
            smtp_operations=False,
            email_poster_winner=False,
            email_poster_operations=False,
            webhook=False,
        )
    code_route = next(route for route in current if route["event_type"] == "code_issued")
    code_route["smtp_winner"] = True
    code_route["email_poster_operations"] = True
    saved = client.put(
        "/api/admin/notification-routing",
        headers=ADMIN,
        json={"routes": current},
    )
    assert saved.status_code == 200

    with Session(test_engine) as session:
        jobs = create_notification_jobs(
            session,
            event_type="code_issued",
            text_rendered="纯文本",
            winner_email="winner@example.com",
        )
        assert [(job.channel, job.destination) for job in jobs] == [
            (NotificationChannel.EMAIL, "winner@example.com"),
            (NotificationChannel.EMAIL_POSTER, "operations@example.com"),
        ]
        assert create_notification_jobs(
            session,
            event_type="redemption_ready",
            text_rendered="纯文本",
            winner_email="winner@example.com",
        ) == []


def test_routing_update_requires_every_event() -> None:
    response = client.put(
        "/api/admin/notification-routing",
        headers=ADMIN,
        json={
            "routes": [
                {
                    "event_type": "code_issued",
                    "smtp_winner": True,
                }
            ]
            * 5
        },
    )
    assert response.status_code == 422


def test_smtp_message_contains_text_and_html_alternatives(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from_email", "sender@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    monkeypatch.setattr(settings, "smtp_username", "")
    sent = []

    class FakeSmtp:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(worker.smtplib, "SMTP", FakeSmtp)
    job = NotificationJob(
        event_type="code_issued",
        channel=NotificationChannel.EMAIL,
        destination="recipient@example.com",
        text_rendered="纯文本",
        html_rendered="<p>HTML</p>",
        status=NotificationStatus.PENDING,
    )
    worker.send_email(job)
    assert len(sent) == 1
    assert sent[0].get_body(preferencelist=("plain",)).get_content().strip() == "纯文本"
    assert sent[0].get_body(preferencelist=("html",)).get_content().strip() == "<p>HTML</p>"


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
