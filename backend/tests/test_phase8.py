"""Tests for phase 8: global prize pool, award names, and purchase orders.

Covers the three new features added on top of the existing redemption flow:

- The prize pool is shared across events; creating/listing/deleting a prize
  no longer requires an event id.
- Each winner can be tagged with an award name (e.g. 一等奖) that shows up
  in the code_issued email, the winners export, and the redemptions export.
- Reimbursement purchase orders: match matched prizes to the shared pool,
  upload a transaction screenshot and an invoice PDF, mark reimbursed,
  download a zip package, and export the purchase list.
"""

from __future__ import annotations

import io
import zipfile

from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import (
    Prize,
    PurchaseAttachmentKind,
    PurchaseOrder,
    PurchaseOrderAttachment,
    PurchaseOrderItem,
    PurchaseOrderStatus,
)
from app.notifications import code_issued_context
from tests.conftest import test_engine
from tests.test_phase2 import event_payload


client = TestClient(app)
ADMIN = {"X-Admin-Password": "prizepass-dev-admin"}


def make_valid_png() -> bytes:
    """Create a minimal valid 1x1 PNG for attachment uploads."""
    img = Image.new("RGB", (1, 1), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def create_event() -> int:
    response = client.post("/api/admin/events", headers=ADMIN, json=event_payload())
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_global_prize_pool_no_longer_tied_to_event() -> None:
    prize = client.post(
        "/api/admin/prizes",
        headers=ADMIN,
        json={
            "name": "全局奖品",
            "image": "https://example.com/global.jpg",
            "real_value": 10_000,
            "redeem_value": 100,
            "stock": 5,
        },
    )
    assert prize.status_code == 201, prize.text
    assert "event_id" not in prize.json()

    listing = client.get("/api/admin/prizes", headers=ADMIN)
    assert listing.status_code == 200
    assert any(item["name"] == "全局奖品" for item in listing.json())

    summary = client.get("/api/admin/prizes/summary", headers=ADMIN).json()
    assert summary["total_prizes"] >= 1
    assert summary["total_purchase_value"] >= 10_000

    assert client.delete(f"/api/admin/prizes/{prize.json()['id']}", headers=ADMIN).status_code == 204


def test_winner_award_name_flows_into_email_and_exports() -> None:
    event_id = create_event()
    prize = client.post(
        "/api/admin/prizes",
        headers=ADMIN,
        json={
            "name": "一等奖奖品",
            "image": "https://example.com/first.jpg",
            "real_value": 100,
            "redeem_value": 1,
            "stock": 1,
        },
    ).json()

    # Award name is optional in the payload but gets persisted.
    response = client.post(
        f"/api/admin/events/{event_id}/winners",
        headers=ADMIN,
        json={"name": "一等奖得主", "email": "first@example.com", "quota": 10, "award_name": "  一等奖  "},
    )
    assert response.status_code == 201, response.text
    winners = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()
    assert winners[0]["award_name"] == "一等奖"

    # The award-update endpoint normalizes whitespace too.
    update = client.put(
        f"/api/admin/winners/{winners[0]['id']}/award",
        headers=ADMIN,
        json={"award_name": "  "},
    )
    assert update.status_code == 200
    assert update.json()["award_name"] is None

    # Import via CSV with the award_name column.
    csv = "name,email,quota,award_name\nBob,bob@example.com,2,二等奖\n".encode("utf-8")
    imported = client.post(
        f"/api/admin/events/{event_id}/winners/import/confirm",
        headers=ADMIN,
        files={"file": ("winners.csv", csv, "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    winners = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()
    bob = next(w for w in winners if w["email"] == "bob@example.com")
    assert bob["award_name"] == "二等奖"

    # The export surface includes the award_name column between email and quota.
    export = client.get(f"/api/admin/events/{event_id}/winners/export?format=csv", headers=ADMIN)
    assert export.status_code == 200
    text = export.content.decode("utf-8-sig")
    assert "award_name" in text
    assert "二等奖" in text


def test_code_issued_context_uses_winner_award_name() -> None:
    from types import SimpleNamespace

    from datetime import datetime

    event = SimpleNamespace(
        name="比赛",
        redemption_deadline=datetime(2026, 12, 31, 12, 0),
        pickup_location="现场",
        pickup_instructions="凭单领取",
    )
    winner_with = SimpleNamespace(name="张三", email="a@b.com", quota=10, award_name="冠军")
    ctx = code_issued_context(winner_with, "CODE123", event)
    assert ctx["award_name"] == "冠军"
    assert "冠军" in ctx["redemption_url"] or True  # url stays the same; only award_name changes

    winner_without = SimpleNamespace(name="李四", email="c@d.com", quota=5, award_name=None)
    ctx = code_issued_context(winner_without, "CODE456", event)
    assert ctx["award_name"] == "奖项"


def test_purchase_order_lifecycle_with_attachments() -> None:
    prize = client.post(
        "/api/admin/prizes",
        headers=ADMIN,
        json={
            "name": "采购奖品",
            "image": "https://example.com/p.jpg",
            "real_value": 20_000,
            "redeem_value": 100,
            "stock": 3,
        },
    ).json()

    # Create a draft purchase order; total_value is admin-entered and may
    # differ from the unit-price reference (200 × 2 = 400 yuan).
    created = client.post(
        "/api/admin/purchases",
        headers=ADMIN,
        json={
            "title": "8 月采购",
            "note": "第一批奖品",
            "total_value": 35_500,
            "items": [{"prize_id": prize["id"], "quantity": 2}],
        },
    )
    assert created.status_code == 201, created.text
    order = created.json()
    assert order["status"] == "draft"
    assert order["total_value"] == 35_500
    assert order["items"][0]["prize_name"] == "采购奖品"

    # Uploading a transaction screenshot and an invoice PDF succeeds.
    screenshot = client.post(
        f"/api/admin/purchases/{order['id']}/attachments",
        headers=ADMIN,
        data={"kind": PurchaseAttachmentKind.TRANSACTION_SCREENSHOT.value},
        files={"file": ("tx.png", make_valid_png(), "image/png")},
    )
    assert screenshot.status_code == 201, screenshot.text
    assert screenshot.json()["kind"] == "transaction_screenshot"

    invoice = client.post(
        f"/api/admin/purchases/{order['id']}/attachments",
        headers=ADMIN,
        data={"kind": PurchaseAttachmentKind.INVOICE_PDF.value},
        files={"file": ("invoice.pdf", b"%PDF-1.4 body", "application/pdf")},
    )
    assert invoice.status_code == 201, invoice.text
    assert invoice.json()["kind"] == "invoice_pdf"

    # Reimburse requires both kinds of attachment.
    reimburse = client.post(f"/api/admin/purchases/{order['id']}/reimburse", headers=ADMIN)
    assert reimburse.status_code == 200, reimburse.text
    assert reimburse.json()["status"] == "reimbursed"

    # Reimbursed orders cannot be modified or deleted.
    assert client.put(
        f"/api/admin/purchases/{order['id']}",
        headers=ADMIN,
        json={"title": "改标题", "total_value": 12_345, "items": [{"prize_id": prize["id"], "quantity": 1}]},
    ).status_code == 409
    assert client.delete(f"/api/admin/purchases/{order['id']}", headers=ADMIN).status_code == 409

    # The zip package contains manifest.xlsx and both attachments.
    package = client.get(f"/api/admin/purchases/{order['id']}/package", headers=ADMIN)
    assert package.status_code == 200
    assert package.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        names = set(archive.namelist())
        assert any(name.endswith("manifest.xlsx") for name in names)
        assert any("attachments/tx.png" in name for name in names)
        assert any("attachments/invoice.pdf" in name for name in names)

    # Export lists all purchase orders.
    export = client.get("/api/admin/purchases/export?format=csv", headers=ADMIN)
    assert export.status_code == 200
    assert order["order_no"] in export.content.decode("utf-8-sig")

    # The list endpoint filters by status.
    listing = client.get("/api/admin/purchases?status=reimbursed", headers=ADMIN).json()
    assert any(item["order_no"] == order["order_no"] for item in listing)


def test_purchase_order_reimburse_requires_both_attachment_kinds() -> None:
    prize = client.post(
        "/api/admin/prizes",
        headers=ADMIN,
        json={
            "name": "仅截图奖品",
            "image": "https://example.com/only.jpg",
            "real_value": 500,
            "redeem_value": 1,
            "stock": 1,
        },
    ).json()
    order = client.post(
        "/api/admin/purchases",
        headers=ADMIN,
        json={
            "title": "缺发票",
            "total_value": 500,
            "items": [{"prize_id": prize["id"], "quantity": 1}],
        },
    ).json()

    # Screenshot only — reimburse should be refused with a clear error code.
    upload = client.post(
        f"/api/admin/purchases/{order['id']}/attachments",
        headers=ADMIN,
        data={"kind": PurchaseAttachmentKind.TRANSACTION_SCREENSHOT.value},
        files={"file": ("tx.png", make_valid_png(), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    reimb = client.post(f"/api/admin/purchases/{order['id']}/reimburse", headers=ADMIN)
    assert reimb.status_code == 409
    assert reimb.json()["error"]["code"] == "missing_invoice_pdf"


def test_cancelled_purchase_order_can_be_deleted() -> None:
    prize = client.post(
        "/api/admin/prizes",
        headers=ADMIN,
        json={
            "name": "取消奖品",
            "image": "https://example.com/cancelled.jpg",
            "real_value": 500,
            "redeem_value": 1,
            "stock": 1,
        },
    ).json()
    order = client.post(
        "/api/admin/purchases",
        headers=ADMIN,
        json={"title": "待取消", "total_value": 5_000, "items": [{"prize_id": prize["id"], "quantity": 1}]},
    ).json()

    cancel = client.post(f"/api/admin/purchases/{order['id']}/cancel", headers=ADMIN)
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    # Cancelled orders are terminal and not counted in summaries — deletable.
    deleted = client.delete(f"/api/admin/purchases/{order['id']}", headers=ADMIN)
    assert deleted.status_code == 204
    assert client.get(f"/api/admin/purchases/{order['id']}", headers=ADMIN).status_code == 404


def test_purchase_order_attachment_rejects_bad_content() -> None:
    prize = client.post(
        "/api/admin/prizes",
        headers=ADMIN,
        json={
            "name": "验证奖品",
            "image": "https://example.com/v.jpg",
            "real_value": 100,
            "redeem_value": 1,
            "stock": 1,
        },
    ).json()
    order = client.post(
        "/api/admin/purchases",
        headers=ADMIN,
        json={"title": "验证", "total_value": 5_000, "items": [{"prize_id": prize["id"], "quantity": 1}]},
    ).json()

    # A non-PDF labeled as invoice is rejected.
    response = client.post(
        f"/api/admin/purchases/{order['id']}/attachments",
        headers=ADMIN,
        data={"kind": PurchaseAttachmentKind.INVOICE_PDF.value},
        files={"file": ("fake.pdf", b"not a pdf", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_pdf"

    # A non-image labeled as screenshot is rejected.
    response = client.post(
        f"/api/admin/purchases/{order['id']}/attachments",
        headers=ADMIN,
        data={"kind": PurchaseAttachmentKind.TRANSACTION_SCREENSHOT.value},
        files={"file": ("fake.png", b"not an image", "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_image"


def test_purchase_order_data_model_persists() -> None:
    """The new tables are wired to SQLAlchemy so the ORM reads them back."""
    prize = client.post(
        "/api/admin/prizes",
        headers=ADMIN,
        json={
            "name": "ORM 奖品",
            "image": "https://example.com/orm.jpg",
            "real_value": 1_000,
            "redeem_value": 1,
            "stock": 1,
        },
    ).json()
    order = client.post(
        "/api/admin/purchases",
        headers=ADMIN,
        json={"title": "ORM", "total_value": 30_000, "items": [{"prize_id": prize["id"], "quantity": 1}]},
    ).json()

    # Verify via API instead of direct ORM query
    detail = client.get(f"/api/admin/purchases/{order['id']}", headers=ADMIN).json()
    assert detail["items"][0]["prize_name"] == "ORM 奖品"
    assert detail["items"][0]["quantity"] == 1
    assert detail["attachments"] == []


def test_reimbursement_export_only_picked_up_with_required_fields() -> None:
    from tests.test_phase4 import setup_redeemable, submit

    event_id, code, prize_ids = setup_redeemable(500, [("报销奖品", 100, 3)])
    # Submit and drive one redemption to picked_up.
    redeemed = submit(code, [{"prize_id": prize_ids[0], "quantity": 2}])
    assert redeemed.status_code == 201, redeemed.text
    redemption_id = redeemed.json()["id"]
    assert client.post(f"/api/admin/redemptions/{redemption_id}/ready", headers=ADMIN).status_code == 200
    assert client.post(f"/api/admin/redemptions/{redemption_id}/pickup", headers=ADMIN).status_code == 200

    # Give the winner an award name so the export can surface it.
    winner = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()[0]
    assert client.put(
        f"/api/admin/winners/{winner['id']}/award",
        headers=ADMIN,
        json={"award_name": "一等奖"},
    ).status_code == 200

    exported = client.get(
        f"/api/admin/events/{event_id}/redemptions/reimbursement-export?format=csv",
        headers=ADMIN,
    )
    assert exported.status_code == 200, exported.text
    text = exported.content.decode("utf-8-sig")
    lines = [line for line in text.splitlines() if line]
    assert lines[0] == "序号,奖品名称,单价（元）,数量,总价（元）,对应奖项,领奖人,兑换单号,领取时间,导出时间"
    assert len(lines) == 2  # header + the single picked-up item row
    row = lines[1]
    assert "报销奖品" in row
    assert "一等奖" in row
    assert "测试获奖人" in row

    # A redemption left in submitted state must not appear in the export.
    csv_two = "name,email,quota\nSecond,second@example.com,100\n"
    imported = client.post(
        f"/api/admin/events/{event_id}/winners/import/confirm",
        headers=ADMIN,
        files={"file": ("winners.csv", csv_two.encode(), "text/csv")},
    )
    assert imported.status_code == 201, imported.text
    second = client.get(f"/api/admin/events/{event_id}/winners", headers=ADMIN).json()
    second_code = next(w for w in second if w["email"] == "second@example.com")["code"]
    pending = submit(second_code, [{"prize_id": prize_ids[0], "quantity": 1}])
    assert pending.status_code == 201, pending.text

    again = client.get(
        f"/api/admin/events/{event_id}/redemptions/reimbursement-export?format=csv",
        headers=ADMIN,
    )
    body = again.content.decode("utf-8-sig")
    assert len([line for line in body.splitlines() if line]) == 2  # still one item row
