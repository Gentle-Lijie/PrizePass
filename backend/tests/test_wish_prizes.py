"""Tests for wish-generated prizes: backfill endpoints and purchase orders.

Covers the feature that materializes custom wishes as catalog prize entries:

- POST /api/admin/wishes/{id}/create-prize is idempotent and rejects non-wishes.
- GET /api/admin/wishes/unmatched lists only wishes without a generated prize.
- A wish prize can be referenced by a purchase order (the reimbursement gap).
- The seeded placeholder image survives prize edits.
"""

from __future__ import annotations

import csv
import io

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.main import app
from app.models import Prize, Redemption
from app.wishes import PLACEHOLDER_IMAGE
from tests.conftest import test_engine
from tests.test_phase2 import event_payload
from tests.test_phase4 import setup_redeemable, submit


client = TestClient(app)
ADMIN = {"X-Admin-Password": "prizepass-dev-admin"}


def submit_wish(code: str, name: str = "空气炸锅", price: int = 49900) -> object:
    return client.post(
        "/api/public/redemptions",
        headers={"X-Redemption-Code": code},
        json={
            "contact_name": "张三",
            "contact_phone": "+86 138-0013-8000",
            "note": None,
            "items": [],
            "custom_name": name,
            "custom_url": "https://item.jd.com/100000000002.html",
            "custom_note": "白色",
            "custom_price": price,
        },
    )


def setup_two_wishes() -> tuple[int, list[dict]]:
    """One event, two winners, two submitted wishes."""
    created = client.post("/api/admin/events", headers=ADMIN, json=event_payload())
    event_id = created.json()["id"]
    assert client.put(
        f"/api/admin/events/{event_id}", headers=ADMIN, json=event_payload("active")
    ).status_code == 200
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["name", "email", "quota"])
    writer.writerow(["获奖人甲", "a@example.com", 500])
    writer.writerow(["获奖人乙", "b@example.com", 500])
    imported = client.post(
        f"/api/admin/events/{event_id}/winners/import/confirm",
        headers=ADMIN,
        files={"file": ("winners.csv", stream.getvalue().encode(), "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    winners = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()
    wishes = []
    for winner in winners:
        response = submit_wish(winner["code"])
        assert response.status_code == 201, response.text
        wishes.append(response.json())
    return event_id, wishes


def test_create_prize_endpoint_is_idempotent() -> None:
    _, code, _ = setup_redeemable(500, [("奖品甲", 200, 2)])
    wish = submit_wish(code)
    assert wish.status_code == 201, wish.text
    redemption_id = wish.json()["id"]

    first = client.post(f"/api/admin/wishes/{redemption_id}/create-prize", headers=ADMIN)
    assert first.status_code == 201, first.text
    prize = first.json()
    assert prize["name"] == "空气炸锅（测试获奖人）"
    assert prize["image"] == PLACEHOLDER_IMAGE
    assert prize["real_value"] == 49900
    assert prize["origin_redemption_id"] == redemption_id
    assert prize["is_active"] is False

    # Repeating the call returns the same prize instead of a duplicate.
    second = client.post(f"/api/admin/wishes/{redemption_id}/create-prize", headers=ADMIN)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == prize["id"]

    # Non-wish redemptions are rejected (uses a fresh code since the wish consumed this one).
    _, code2, prizes = setup_redeemable(500, [("奖品乙", 200, 2)])
    response = submit(code2, [{"prize_id": prizes[0], "quantity": 1}])
    assert response.status_code == 201, response.text
    rejected = client.post(
        f"/api/admin/wishes/{response.json()['id']}/create-prize", headers=ADMIN
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "not_a_wish"


def test_unmatched_wishes_listing() -> None:
    event_id, wishes = setup_two_wishes()
    listed = client.get("/api/admin/wishes/unmatched", headers=ADMIN).json()
    ids = {item["redemption_id"] for item in listed}
    assert {wish["id"] for wish in wishes} <= ids
    by_id = {item["redemption_id"]: item for item in listed}
    for wish in wishes:
        entry = by_id[wish["id"]]
        assert entry["custom_name"] == "空气炸锅"
        assert entry["custom_price"] == 49900
        assert entry["winner_name"] in ("获奖人甲", "获奖人乙")

    # Adopting one wish generates its prize and drops it from the listing.
    adopted = client.post(f"/api/admin/redemptions/{wishes[0]['id']}/ready", headers=ADMIN)
    assert adopted.status_code == 200
    assert adopted.json()["status"] == "procuring"
    listed = client.get("/api/admin/wishes/unmatched", headers=ADMIN).json()
    assert wishes[0]["id"] not in {item["redemption_id"] for item in listed}
    assert wishes[1]["id"] in {item["redemption_id"] for item in listed}

    # Cancelled (rejected) wishes never show up for backfill.
    rejected = client.post(
        f"/api/admin/redemptions/{wishes[1]['id']}/cancel",
        headers=ADMIN,
        json={"reason": "预算不足"},
    )
    assert rejected.status_code == 200, rejected.text
    listed = client.get("/api/admin/wishes/unmatched", headers=ADMIN).json()
    assert wishes[1]["id"] not in {item["redemption_id"] for item in listed}


def test_purchase_order_with_wish_prize() -> None:
    _, code, _ = setup_redeemable(500, [("奖品甲", 200, 2)])
    wish = submit_wish(code)
    assert wish.status_code == 201, wish.text
    prize = client.post(
        f"/api/admin/wishes/{wish.json()['id']}/create-prize", headers=ADMIN
    ).json()

    # The gap this feature closes: wish prizes are referenceable on purchase orders.
    created = client.post(
        "/api/admin/purchases",
        headers=ADMIN,
        json={
            "title": "心愿采购",
            "note": None,
            "total_value": 49_900,
            "items": [{"prize_id": prize["id"], "quantity": 1}],
        },
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["items"][0]["prize_id"] == prize["id"]
    assert order["items"][0]["prize_name"] == "空气炸锅（测试获奖人）"


def test_placeholder_image_survives_prize_edit() -> None:
    _, code, _ = setup_redeemable(500, [("奖品甲", 200, 2)])
    wish = submit_wish(code)
    assert wish.status_code == 201, wish.text
    prize = client.post(
        f"/api/admin/wishes/{wish.json()['id']}/create-prize", headers=ADMIN
    ).json()

    placeholder = get_settings().upload_dir / "prizes" / "placeholder.png"
    assert placeholder.is_file(), "app startup should seed the placeholder image"

    # Replacing the last reference to the placeholder must not delete the file.
    edited = client.put(
        f"/api/admin/prizes/{prize['id']}",
        headers=ADMIN,
        json={
            "name": prize["name"],
            "image": "https://example.com/real.jpg",
            "real_value": 49900,
            "redeem_value": 1,
            "stock": 0,
            "description": None,
            "tag": "心愿奖品",
            "is_active": False,
        },
    )
    assert edited.status_code == 200, edited.text
    assert placeholder.is_file()

    with Session(test_engine) as session:
        assert session.scalar(select(Prize).where(Prize.image == PLACEHOLDER_IMAGE)) is None


def test_reimbursement_export_includes_picked_up_wishes() -> None:
    event_id, code, _ = setup_redeemable(500, [("奖品甲", 200, 2)])
    wish = submit_wish(code, name="降噪耳机", price=129900)
    assert wish.status_code == 201, wish.text
    redemption_id = wish.json()["id"]
    # Drive the wish through the full flow: accept (procuring) → stock (ready) → pickup.
    assert client.post(f"/api/admin/redemptions/{redemption_id}/ready", headers=ADMIN).status_code == 200
    assert client.post(f"/api/admin/redemptions/{redemption_id}/stock", headers=ADMIN).status_code == 200
    assert client.post(f"/api/admin/redemptions/{redemption_id}/pickup", headers=ADMIN).status_code == 200

    exported = client.get(
        f"/api/admin/events/{event_id}/redemptions/reimbursement-export?format=csv",
        headers=ADMIN,
    )
    assert exported.status_code == 200, exported.text
    text = exported.content.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if line]
    assert lines[0].startswith("序号,奖品名称")
    row = lines[1]
    assert "自定义：降噪耳机" in row
    assert "1299.00" in row
    assert "测试获奖人" in row
    assert wish.json()["order_no"] in row


def test_repeated_wish_submission_refreshes_unreferenced_prize() -> None:
    """Rejecting and re-submitting a wish keeps a single, refreshed prize row."""
    _, code, _ = setup_redeemable(500, [("奖品甲", 200, 2)])
    first = submit_wish(code, name="旧心愿", price=9900)
    assert first.status_code == 201, first.text
    redemption_id = first.json()["id"]

    adopted = client.post(f"/api/admin/redemptions/{redemption_id}/ready", headers=ADMIN)
    assert adopted.status_code == 200
    prize_id = adopted.json()["generated_prize_id"]

    rejected = client.post(
        f"/api/admin/redemptions/{redemption_id}/cancel",
        headers=ADMIN,
        json={"reason": "换个心愿"},
    )
    assert rejected.status_code == 200, rejected.text

    # The winner re-submits (same redemption row is reused).
    resubmitted = submit_wish(code, name="新心愿", price=19900)
    assert resubmitted.status_code == 201, resubmitted.text
    assert resubmitted.json()["id"] == redemption_id

    re_adopted = client.post(f"/api/admin/redemptions/{redemption_id}/ready", headers=ADMIN)
    assert re_adopted.status_code == 200, re_adopted.text
    assert re_adopted.json()["generated_prize_id"] == prize_id

    with Session(test_engine) as session:
        prizes = session.scalars(
            select(Prize).where(Prize.origin_redemption_id == redemption_id)
        ).all()
        assert len(prizes) == 1
        assert prizes[0].name == "新心愿（测试获奖人）"
        assert prizes[0].real_value == 19900
        redemption = session.get(Redemption, redemption_id)
        assert redemption is not None and redemption.status.value == "procuring"
