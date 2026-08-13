import csv
import io
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.models import (
    CodeStatus,
    NotificationJob,
    Prize,
    Redemption,
    RedemptionCode,
    RedemptionItem,
)
from tests.conftest import test_engine
from tests.test_phase2 import event_payload


client = TestClient(app)
ADMIN = {"X-Admin-Password": "prizepass-dev-admin"}


def setup_redeemable(quota: int, prize_specs: list[tuple[str, int, int]]) -> tuple[int, str, list[int]]:
    created = client.post("/api/admin/events", headers=ADMIN, json=event_payload())
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    assert client.put(
        f"/api/admin/events/{event_id}", headers=ADMIN, json=event_payload("active")
    ).status_code == 200
    prize_ids = []
    for name, redeem_value, stock in prize_specs:
        response = client.post(
            f"/api/admin/events/{event_id}/prizes",
            headers=ADMIN,
            json={
                "name": name,
                "image": f"https://example.com/{name}.jpg",
                "real_value": redeem_value * 100,
                "redeem_value": redeem_value,
                "stock": stock,
                "description": name,
            },
        )
        assert response.status_code == 201, response.text
        prize_ids.append(response.json()["id"])
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["name", "email", "quota"])
    writer.writerow(["测试获奖人", "winner@example.com", quota])
    imported = client.post(
        f"/api/admin/events/{event_id}/winners/import/confirm",
        headers=ADMIN,
        files={"file": ("winners.csv", stream.getvalue().encode(), "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    winner = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()[0]
    return event_id, winner["code"], prize_ids


def submit(code: str, items: list[dict]) -> object:
    return client.post(
        "/api/public/redemptions",
        headers={"X-Redemption-Code": code},
        json={
            "contact_name": "张三",
            "contact_phone": "+86 138-0013-8000",
            "note": "下午领取",
            "items": items,
        },
    )


def test_public_endpoints_require_header_and_filter_prizes() -> None:
    _, code, prizes = setup_redeemable(500, [("可兑换", 200, 2), ("太贵", 600, 2), ("无库存", 100, 0)])
    assert client.post("/api/public/code/verify").status_code == 401
    verified = client.post("/api/public/code/verify", headers={"X-Redemption-Code": code})
    assert verified.status_code == 200
    assert verified.json()["quota"] == 500
    context = client.get("/api/public/redemption/context", headers={"X-Redemption-Code": code})
    assert context.status_code == 200
    visible = client.get("/api/public/redemption/prizes", headers={"X-Redemption-Code": code})
    assert visible.status_code == 200
    assert [prize["id"] for prize in visible.json()] == [prizes[0]]
    assert "set-cookie" not in visible.headers


def test_multi_prize_redemption_is_atomic_and_snapshotted() -> None:
    _, code, prizes = setup_redeemable(500, [("奖品甲", 200, 2), ("奖品乙", 100, 3)])
    response = submit(code, [{"prize_id": prizes[0], "quantity": 1}, {"prize_id": prizes[1], "quantity": 2}])
    assert response.status_code == 201, response.text
    assert response.json()["total_redeem_value"] == 400
    assert response.json()["unused_quota"] == 100

    with Session(test_engine) as session:
        redemption = session.scalar(select(Redemption))
        items = session.scalars(select(RedemptionItem).order_by(RedemptionItem.id)).all()
        code_row = session.scalar(select(RedemptionCode).where(RedemptionCode.code == code))
        stocks = session.scalars(select(Prize.stock).order_by(Prize.id)).all()
        jobs = session.scalars(
            select(NotificationJob).where(NotificationJob.event_type == "redemption_submitted")
        ).all()
        assert redemption is not None and redemption.total_redeem_value == 400
        assert len(items) == 2
        assert [item.line_redeem_value for item in items] == [200, 200]
        assert code_row.status is CodeStatus.REDEEMED
        assert stocks == [1, 1]
        assert len(jobs) == 2 and jobs[0].text_rendered == jobs[1].text_rendered

    edited = {
        "name": "改名后的奖品",
        "image": "https://example.com/changed.jpg",
        "real_value": 99900,
        "redeem_value": 999,
        "stock": 1,
        "description": "修改",
    }
    assert client.put(f"/api/admin/prizes/{prizes[0]}", headers=ADMIN, json=edited).status_code == 200
    with Session(test_engine) as session:
        snapshot = session.scalar(select(RedemptionItem).where(RedemptionItem.prize_id == prizes[0]))
        assert snapshot.prize_name_snapshot == "奖品甲"
        assert snapshot.redeem_value_snapshot == 200


def test_over_quota_and_insufficient_stock_rollback_everything() -> None:
    _, code, prizes = setup_redeemable(500, [("超额奖品", 501, 2), ("少库存", 100, 1)])
    over = submit(code, [{"prize_id": prizes[0], "quantity": 1}])
    assert over.status_code == 409
    insufficient = submit(code, [{"prize_id": prizes[1], "quantity": 2}])
    assert insufficient.status_code == 409
    with Session(test_engine) as session:
        assert session.scalar(select(func.count(Redemption.id))) == 0
        assert session.scalars(select(Prize.stock).order_by(Prize.id)).all() == [2, 1]
        assert session.scalar(select(RedemptionCode).where(RedemptionCode.code == code)).status is CodeStatus.ISSUED


def test_duplicate_item_rejected_without_writes() -> None:
    _, code, prizes = setup_redeemable(500, [("奖品", 100, 3)])
    response = submit(code, [{"prize_id": prizes[0], "quantity": 1}, {"prize_id": prizes[0], "quantity": 1}])
    assert response.status_code == 422
    with Session(test_engine) as session:
        assert session.scalar(select(func.count(Redemption.id))) == 0
        assert session.get(Prize, prizes[0]).stock == 3


def test_concurrent_same_code_only_one_request_succeeds() -> None:
    _, code, prizes = setup_redeemable(500, [("并发奖品", 100, 2)])
    payload = [{"prize_id": prizes[0], "quantity": 1}]
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: submit(code, payload), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    with Session(test_engine) as session:
        assert session.scalar(select(func.count(Redemption.id))) == 1
        assert session.get(Prize, prizes[0]).stock == 1


def test_closed_event_invalidates_issued_code() -> None:
    event_id, code, _ = setup_redeemable(500, [("奖品", 100, 1)])
    closed = event_payload("closed")
    assert client.put(f"/api/admin/events/{event_id}", headers=ADMIN, json=closed).status_code == 200
    response = client.post("/api/public/code/verify", headers={"X-Redemption-Code": code})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "event_closed"
