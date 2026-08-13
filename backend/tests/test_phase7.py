from datetime import datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.models import NotificationChannel, NotificationJob, RedemptionItem
from app.notifications import code_issued_context
from tests.conftest import test_engine
from tests.test_phase2 import event_payload
from tests.test_phase4 import setup_redeemable, submit


client = TestClient(app)
ADMIN = {"X-Admin-Password": "prizepass-dev-admin"}


def test_code_notification_url_contains_redeem_code() -> None:
    winner = SimpleNamespace(name="测试", email="winner@example.com", quota=300)
    event = SimpleNamespace(
        name="测试比赛",
        redemption_deadline=datetime(2026, 12, 31, 12, 0),
        pickup_location="服务台",
        pickup_instructions="凭单领取",
    )
    context = code_issued_context(winner, "ABCD2345EFGH", event)
    assert context["redemption_url"].endswith("/redeem?code=ABCD2345EFGH")


def test_purchase_summary_uses_snapshot_and_picked_up_status() -> None:
    payload = {**event_payload(), "budget": 12_000}
    created = client.post("/api/admin/events", headers=ADMIN, json=payload)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    assert client.put(
        f"/api/admin/events/{event_id}",
        headers=ADMIN,
        json={**payload, "status": "active"},
    ).status_code == 200
    prize = client.post(
        f"/api/admin/events/{event_id}/prizes",
        headers=ADMIN,
        json={
            "name": "采购价奖品",
            "image": "https://example.com/purchased.jpg",
            "jd_url": "https://item.jd.com/100000000001.html",
            "real_value": 8_000,
            "purchase_value": 5_000,
            "redeem_value": 100,
            "stock": 2,
            "description": None,
        },
    )
    assert prize.status_code == 201, prize.text

    # Reuse the winner import path through a minimal CSV.
    csv_content = b"name,email,quota\nTest,winner@example.com,100\n"
    imported = client.post(
        f"/api/admin/events/{event_id}/winners/import/confirm",
        headers=ADMIN,
        files={"file": ("winners.csv", csv_content, "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    winner = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()[0]
    public_prizes = client.get(
        "/api/public/redemption/prizes",
        headers={"X-Redemption-Code": winner["code"]},
    )
    assert public_prizes.status_code == 200
    assert public_prizes.json()[0]["jd_url"] == "https://item.jd.com/100000000001.html"

    initial = client.get(
        f"/api/admin/events/{event_id}/prizes/summary", headers=ADMIN
    ).json()
    assert initial == {
        "total_purchase_value": 16_000,
        "claimed_purchase_value": 0,
        "budget": 12_000,
    }

    redeemed = submit(winner["code"], [{"prize_id": prize.json()["id"], "quantity": 1}])
    assert redeemed.status_code == 201, redeemed.text
    summary = client.get(
        f"/api/admin/events/{event_id}/prizes/summary", headers=ADMIN
    ).json()
    assert summary["total_purchase_value"] == 16_000
    assert summary["claimed_purchase_value"] == 0
    with Session(test_engine) as session:
        item = session.scalar(select(RedemptionItem))
        assert item.real_value_snapshot == 8_000
        assert item.purchase_value_snapshot == 5_000

    redemption_id = redeemed.json()["id"]
    assert client.post(
        f"/api/admin/redemptions/{redemption_id}/ready", headers=ADMIN
    ).status_code == 200
    assert client.post(
        f"/api/admin/redemptions/{redemption_id}/pickup", headers=ADMIN
    ).status_code == 200
    claimed = client.get(
        f"/api/admin/events/{event_id}/prizes/summary", headers=ADMIN
    ).json()
    assert claimed["claimed_purchase_value"] == 8_000


def test_winner_resend_adjust_quota_and_revoke_code() -> None:
    event_id, code, _ = setup_redeemable(500, [("奖品", 100, 1)])
    winner = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()[0]

    adjusted = client.put(
        f"/api/admin/winners/{winner['id']}/quota",
        headers=ADMIN,
        json={"quota": 650},
    )
    assert adjusted.status_code == 200
    assert adjusted.json()["quota"] == 650
    assert client.post(
        "/api/public/code/verify", headers={"X-Redemption-Code": code}
    ).json()["quota"] == 650

    with Session(test_engine) as session:
        before = session.scalar(select(func.count(NotificationJob.id)))
    resent = client.post(
        f"/api/admin/winners/{winner['id']}/notifications/resend",
        headers=ADMIN,
        json={"channels": ["email"]},
    )
    assert resent.status_code == 201, resent.text
    assert resent.json() == {"queued": 1, "channels": ["email"]}
    with Session(test_engine) as session:
        assert session.scalar(select(func.count(NotificationJob.id))) == before + 1
        newest = session.scalars(
            select(NotificationJob).order_by(NotificationJob.id.desc()).limit(1)
        ).one()
        assert newest.channel is NotificationChannel.EMAIL

    revoked = client.post(
        f"/api/admin/winners/{winner['id']}/code/revoke", headers=ADMIN
    )
    assert revoked.status_code == 200
    assert revoked.json()["code_status"] == "disabled"
    disabled = client.post(
        "/api/public/code/verify", headers={"X-Redemption-Code": code}
    )
    assert disabled.status_code == 409
    assert disabled.json()["error"]["code"] == "redemption_code_disabled"
    assert client.put(
        f"/api/admin/winners/{winner['id']}/quota",
        headers=ADMIN,
        json={"quota": 700},
    ).status_code == 409
    assert client.post(
        f"/api/admin/winners/{winner['id']}/notifications/resend",
        headers=ADMIN,
        json={"channels": ["email"]},
    ).status_code == 409
