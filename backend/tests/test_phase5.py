import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import app
from app.models import CodeStatus, NotificationJob, Prize, Redemption, RedemptionCode
from tests.conftest import test_engine
from tests.test_phase4 import setup_redeemable, submit


client = TestClient(app)
ADMIN = {"X-Admin-Password": "prizepass-dev-admin"}


def submitted_redemption() -> tuple[int, str, list[int], int]:
    event_id, code, prizes = setup_redeemable(500, [("奖品甲", 200, 2), ("奖品乙", 100, 3)])
    response = submit(code, [{"prize_id": prizes[0], "quantity": 1}, {"prize_id": prizes[1], "quantity": 2}])
    assert response.status_code == 201, response.text
    return event_id, code, prizes, response.json()["id"]


def test_ready_then_cancel_restores_inventory_and_code() -> None:
    _, code, prizes, redemption_id = submitted_redemption()
    ready = client.post(f"/api/admin/redemptions/{redemption_id}/ready", headers=ADMIN)
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"
    cancelled = client.post(f"/api/admin/redemptions/{redemption_id}/cancel", headers=ADMIN)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancelled_at"] is not None

    with Session(test_engine) as session:
        assert session.get(Prize, prizes[0]).stock == 2
        assert session.get(Prize, prizes[1]).stock == 3
        code_row = session.scalar(select(RedemptionCode).where(RedemptionCode.code == code))
        assert code_row.status is CodeStatus.ISSUED
        assert code_row.redeemed_at is None
        assert session.scalar(
            select(func.count(NotificationJob.id)).where(
                NotificationJob.event_type == "redemption_ready"
            )
        ) == 2


def test_cancelled_code_can_submit_a_new_redemption() -> None:
    _, code, prizes, redemption_id = submitted_redemption()
    first_order = client.get(f"/api/admin/redemptions/{redemption_id}", headers=ADMIN).json()["order_no"]
    assert client.post(f"/api/admin/redemptions/{redemption_id}/cancel", headers=ADMIN).status_code == 200
    second = submit(code, [{"prize_id": prizes[0], "quantity": 1}])
    assert second.status_code == 201, second.text
    assert second.json()["order_no"] != first_order
    with Session(test_engine) as session:
        assert session.scalar(select(func.count(Redemption.id))) == 1
        assert session.get(Prize, prizes[0]).stock == 1
        assert session.get(Prize, prizes[1]).stock == 3
        assert session.scalar(
            select(func.count(NotificationJob.id)).where(
                NotificationJob.event_type == "redemption_cancelled"
            )
        ) == 2


def test_picked_up_is_terminal() -> None:
    _, _, prizes, redemption_id = submitted_redemption()
    assert client.post(f"/api/admin/redemptions/{redemption_id}/ready", headers=ADMIN).status_code == 200
    picked = client.post(f"/api/admin/redemptions/{redemption_id}/pickup", headers=ADMIN)
    assert picked.status_code == 200
    assert picked.json()["status"] == "picked_up"
    assert picked.json()["picked_up_at"] is not None
    assert client.post(f"/api/admin/redemptions/{redemption_id}/pickup", headers=ADMIN).status_code == 409
    assert client.post(f"/api/admin/redemptions/{redemption_id}/cancel", headers=ADMIN).status_code == 409
    with Session(test_engine) as session:
        assert session.get(Prize, prizes[0]).stock == 1
        assert session.get(Prize, prizes[1]).stock == 1


def test_invalid_direct_pickup_does_not_change_status() -> None:
    _, _, _, redemption_id = submitted_redemption()
    response = client.post(f"/api/admin/redemptions/{redemption_id}/pickup", headers=ADMIN)
    assert response.status_code == 409
    with Session(test_engine) as session:
        assert session.get(Redemption, redemption_id).status.value == "submitted"


def test_list_detail_filter_search_and_expanded_exports() -> None:
    event_id, _, _, redemption_id = submitted_redemption()
    detail = client.get(f"/api/admin/redemptions/{redemption_id}", headers=ADMIN)
    assert detail.status_code == 200
    assert len(detail.json()["items"]) == 2
    order_no = detail.json()["order_no"]
    listed = client.get(
        f"/api/admin/events/{event_id}/redemptions?status=submitted&search={order_no[-6:]}",
        headers=ADMIN,
    )
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [redemption_id]
    assert client.get(
        f"/api/admin/events/{event_id}/redemptions?status=ready", headers=ADMIN
    ).json() == []

    csv_export = client.get(
        f"/api/admin/events/{event_id}/redemptions/export?format=csv", headers=ADMIN
    )
    assert csv_export.status_code == 200
    csv_text = csv_export.content.decode("utf-8-sig")
    assert csv_text.count(order_no) == 2
    xlsx_export = client.get(
        f"/api/admin/events/{event_id}/redemptions/export?format=xlsx", headers=ADMIN
    )
    workbook = load_workbook(io.BytesIO(xlsx_export.content), read_only=True)
    values = list(workbook.active.values)
    assert len(values) == 3
    assert values[1][0] == values[2][0] == order_no
    workbook.close()
