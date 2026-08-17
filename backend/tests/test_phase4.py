import csv
import io
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.models import (
    CodeStatus,
    NotificationChannel,
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
            f"/api/admin/prizes",
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
        prize_id = response.json()["id"]
        prize_ids.append(prize_id)
        # Make this prize available for the event.
        add_response = client.post(
            f"/api/admin/events/{event_id}/prizes/{prize_id}",
            headers=ADMIN,
        )
        assert add_response.status_code == 201, add_response.text
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
    assert [prize["id"] for prize in visible.json()] == prizes
    assert all("stock" not in prize for prize in visible.json())
    assert all("real_value" not in prize for prize in visible.json())
    assert "set-cookie" not in visible.headers


def test_public_prizes_order_by_tag_with_untagged_last() -> None:
    specs = [("生活", 100, 1), ("数码", 100, 1), ("默认", 100, 1)]
    _, code, prizes = setup_redeemable(500, specs)
    tags = {"生活": "2-生活", "数码": "1-数码", "默认": None}
    for prize_id, (name, redeem_value, stock) in zip(prizes, specs):
        response = client.put(
            f"/api/admin/prizes/{prize_id}",
            headers=ADMIN,
            json={
                "name": name,
                "image": f"https://example.com/{name}.jpg",
                "real_value": redeem_value * 100,
                "redeem_value": redeem_value,
                "stock": stock,
                "description": None,
                "tag": tags[name],
            },
        )
        assert response.status_code == 200, response.text
    visible = client.get("/api/public/redemption/prizes", headers={"X-Redemption-Code": code})
    assert visible.status_code == 200
    assert [prize["tag"] for prize in visible.json()] == ["1-数码", "2-生活", None]


def test_public_prizes_hide_off_shelf_and_batch_delete_skips_referenced() -> None:
    event_id, code, prizes = setup_redeemable(500, [("可兑换", 200, 2), ("将下架", 100, 2), ("将删除", 100, 2)])
    redeemable, off_shelf, deletable = prizes
    # Take one prize off-shelf: hidden from the public page, still in the admin list.
    assert client.put(
        f"/api/admin/prizes/{off_shelf}",
        headers=ADMIN,
        json={
            "name": "将下架",
            "image": "https://example.com/将下架.jpg",
            "real_value": 10_000,
            "redeem_value": 100,
            "stock": 2,
            "description": None,
            "is_active": False,
        },
    ).status_code == 200
    visible = client.get("/api/public/redemption/prizes", headers={"X-Redemption-Code": code})
    assert visible.status_code == 200
    assert [prize["id"] for prize in visible.json()] == [redeemable, deletable]

    # Reference one prize through a redemption, then batch-delete both.
    response = submit(code, [{"prize_id": redeemable, "quantity": 1}])
    assert response.status_code == 201, response.text
    result = client.post(
        f"/api/admin/prizes/batch-delete",
        headers=ADMIN,
        json={"ids": [redeemable, deletable]},
    )
    assert result.status_code == 200, result.text
    assert result.json() == {
        "deleted": 1,
        "skipped": [{"id": redeemable, "name": "可兑换"}],
    }


def test_custom_prize_redemption_flow() -> None:
    event_id, code, prizes = setup_redeemable(500, [("奖品甲", 200, 2)])
    base = {
        "contact_name": "张三",
        "contact_phone": "+86 138-0013-8000",
        "note": None,
    }
    # Mixing custom and catalog items, or submitting neither, is rejected.
    mixed = client.post(
        "/api/public/redemptions",
        headers={"X-Redemption-Code": code},
        json={**base, "items": [{"prize_id": prizes[0], "quantity": 1}], "custom_name": "无线键盘"},
    )
    assert mixed.status_code == 422
    empty = client.post(
        "/api/public/redemptions",
        headers={"X-Redemption-Code": code},
        json={**base, "items": []},
    )
    assert empty.status_code == 422

    submitted = client.post(
        "/api/public/redemptions",
        headers={"X-Redemption-Code": code},
        json={
            **base,
            "items": [],
            "custom_name": "无线键盘",
            "custom_url": "https://item.jd.com/100000000001.html",
            "custom_note": "黑色",
            "custom_price": 19900,
        },
    )
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["custom_name"] == "无线键盘"
    assert submitted.json()["total_redeem_value"] == 0
    redemption_id = submitted.json()["id"]

    listed = client.get(f"/api/admin/events/{event_id}/redemptions", headers=ADMIN).json()
    record = next(item for item in listed if item["id"] == redemption_id)
    assert record["items_summary"] == "自定义：无线键盘"
    assert record["custom_url"] == "https://item.jd.com/100000000001.html"
    assert record["custom_price"] == 19900
    wish_text = next(
        job.text_rendered
        for job in Session(test_engine).scalars(
            select(NotificationJob).where(NotificationJob.event_type == "wish_submitted")
        )
        if job.channel == NotificationChannel.EMAIL
    )
    assert "199.00 元" in wish_text

    with Session(test_engine) as session:
        wish_jobs = session.scalars(
            select(NotificationJob).where(NotificationJob.event_type == "wish_submitted")
        ).all()
        assert len(wish_jobs) == 2  # smtp (operations) + webhook; email_poster disabled in tests
        assert all(job.redemption_id == redemption_id for job in wish_jobs)

    # Accept: the ready transition notifies the winner.
    assert client.post(f"/api/admin/redemptions/{redemption_id}/ready", headers=ADMIN).status_code == 200
    with Session(test_engine) as session:
        ready_jobs = session.scalars(
            select(NotificationJob).where(NotificationJob.event_type == "redemption_ready")
        ).all()
        assert ready_jobs and all(job.winner_id is not None for job in ready_jobs)

    # Rejecting a custom prize requires an admin-written reason for the winner email.
    no_reason = client.post(f"/api/admin/redemptions/{redemption_id}/cancel", headers=ADMIN)
    assert no_reason.status_code == 422
    rejected = client.post(
        f"/api/admin/redemptions/{redemption_id}/cancel",
        headers=ADMIN,
        json={"reason": "超出本次活动预算"},
    )
    assert rejected.status_code == 200, rejected.text
    with Session(test_engine) as session:
        code_row = session.scalar(select(RedemptionCode).where(RedemptionCode.code == code))
        assert code_row.status == CodeStatus.ISSUED
        rejected_jobs = session.scalars(
            select(NotificationJob).where(NotificationJob.event_type == "wish_rejected")
        ).all()
        assert rejected_jobs
        assert all("超出本次活动预算" in job.text_rendered for job in rejected_jobs)
        cancelled_jobs = session.scalars(
            select(NotificationJob).where(NotificationJob.event_type == "redemption_cancelled")
        ).all()
        assert not cancelled_jobs


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


def test_over_quota_rolls_back_but_stock_shortage_creates_backorder() -> None:
    _, code, prizes = setup_redeemable(500, [("超额奖品", 501, 2), ("少库存", 100, 1)])
    over = submit(code, [{"prize_id": prizes[0], "quantity": 1}])
    assert over.status_code == 409
    insufficient = submit(code, [{"prize_id": prizes[1], "quantity": 2}])
    assert insufficient.status_code == 201
    with Session(test_engine) as session:
        assert session.scalar(select(func.count(Redemption.id))) == 1
        assert session.scalars(select(Prize.stock).order_by(Prize.id)).all() == [2, -1]
        assert session.scalar(select(RedemptionCode).where(RedemptionCode.code == code)).status is CodeStatus.REDEEMED


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


def _create_draft_event() -> int:
    created = client.post("/api/admin/events", headers=ADMIN, json=event_payload())
    assert created.status_code == 201, created.text
    return created.json()["id"]


def test_importing_winners_auto_opens_draft_event() -> None:
    event_id = _create_draft_event()
    assert client.get(f"/api/admin/events/{event_id}", headers=ADMIN).json()["status"] == "draft"
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["name", "email", "quota"])
    writer.writerow(["获奖人甲", "a@example.com", "300"])
    imported = client.post(
        f"/api/admin/events/{event_id}/winners/import/confirm",
        headers=ADMIN,
        files={"file": ("winners.csv", stream.getvalue().encode(), "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    assert client.get(f"/api/admin/events/{event_id}", headers=ADMIN).json()["status"] == "active"


def test_add_winner_directly_auto_opens_and_issues_code() -> None:
    event_id = _create_draft_event()
    response = client.post(
        f"/api/admin/events/{event_id}/winners",
        headers=ADMIN,
        json={"external_id": None, "name": "直接添加", "email": "direct@example.com", "quota": 200},
    )
    assert response.status_code == 201, response.text
    assert response.json()["imported"] == 1
    assert client.get(f"/api/admin/events/{event_id}", headers=ADMIN).json()["status"] == "active"
    winner = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()[0]
    assert winner["name"] == "直接添加"
    assert winner["quota"] == 200
    assert winner["code_status"] == "issued"


def test_add_winner_rejects_duplicate() -> None:
    event_id = _create_draft_event()
    body = {"external_id": None, "name": "重复", "email": "dup@example.com", "quota": 100}
    assert client.post(f"/api/admin/events/{event_id}/winners", headers=ADMIN, json=body).status_code == 201
    second = client.post(f"/api/admin/events/{event_id}/winners", headers=ADMIN, json=body)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "winner_exists"


def test_add_winner_leaves_active_and_closed_unchanged() -> None:
    for status in ("active", "closed"):
        event_id = _create_draft_event()
        # draft → active (→ closed); the state machine forbids draft → closed directly.
        assert client.put(
            f"/api/admin/events/{event_id}", headers=ADMIN, json=event_payload("active")
        ).status_code == 200
        if status == "closed":
            assert client.put(
                f"/api/admin/events/{event_id}", headers=ADMIN, json=event_payload("closed")
            ).status_code == 200
        response = client.post(
            f"/api/admin/events/{event_id}/winners",
            headers=ADMIN,
            json={"external_id": None, "name": f"人-{status}", "email": f"{status}@example.com", "quota": 50},
        )
        assert response.status_code == 201, response.text
        assert client.get(f"/api/admin/events/{event_id}", headers=ADMIN).json()["status"] == status
