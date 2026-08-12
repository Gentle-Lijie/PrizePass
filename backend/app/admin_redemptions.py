from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_events import get_event_or_404
from .auth import require_admin_password
from .config import get_settings
from .database import get_db
from .http import fail
from .models import (
    CodeStatus,
    Event,
    Prize,
    Redemption,
    RedemptionCode,
    RedemptionItem,
    RedemptionStatus,
    Winner,
)
from .notifications import create_notification_pair, render_template, template_text, utc_now
from .spreadsheets import export_csv, export_xlsx
from .timeutils import utc_iso


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin_password)],
    tags=["admin-redemptions"],
)
DbSession = Annotated[Session, Depends(get_db)]
EXPORT_HEADERS = [
    "order_no",
    "status",
    "winner_name",
    "winner_email",
    "contact_name",
    "contact_phone",
    "note",
    "quota",
    "total_redeem_value",
    "unused_quota",
    "prize_name",
    "real_value",
    "redeem_value",
    "quantity",
    "line_redeem_value",
    "created_at",
    "picked_up_at",
    "cancelled_at",
]


def redemption_or_404(db: Session, redemption_id: int, *, lock: bool = False) -> Redemption:
    statement = select(Redemption).where(Redemption.id == redemption_id)
    if lock:
        statement = statement.with_for_update()
    redemption = db.scalar(statement)
    if redemption is None:
        fail(404, "redemption_not_found", "兑换记录不存在")
    return redemption


def related(db: Session, redemption: Redemption) -> tuple[RedemptionCode, Winner, Event, list[RedemptionItem]]:
    code = db.get(RedemptionCode, redemption.code_id)
    winner = db.get(Winner, code.winner_id) if code else None
    event = db.get(Event, redemption.event_id)
    if code is None or winner is None or event is None:
        fail(500, "invalid_redemption_data", "兑换记录关联数据不完整")
    items = list(
        db.scalars(
            select(RedemptionItem)
            .where(RedemptionItem.redemption_id == redemption.id)
            .order_by(RedemptionItem.id)
        ).all()
    )
    return code, winner, event, items


def item_summary(items: list[RedemptionItem]) -> str:
    return "、".join(f"{item.prize_name_snapshot} × {item.quantity}" for item in items)


def status_context(
    redemption: Redemption,
    code: RedemptionCode,
    winner: Winner,
    event: Event,
    items: list[RedemptionItem],
) -> dict[str, str | int]:
    return {
        "winner_name": winner.name,
        "winner_email": winner.email,
        "event_name": event.name,
        "code": code.code,
        "quota": redemption.quota_snapshot,
        "redemption_url": f"{get_settings().public_base_url.rstrip('/')}/redeem",
        "deadline": event.redemption_deadline.isoformat(sep=" "),
        "order_no": redemption.order_no,
        "items_summary": item_summary(items),
        "total_redeem_value": redemption.total_redeem_value,
        "unused_quota": redemption.quota_snapshot - redemption.total_redeem_value,
        "status": redemption.status.value,
        "pickup_location": redemption.pickup_location_snapshot,
        "pickup_instructions": redemption.pickup_instructions_snapshot,
    }


def serialize_redemption(
    redemption: Redemption,
    winner: Winner,
    items: list[RedemptionItem],
    *,
    detail: bool = False,
) -> dict:
    result = {
        "id": redemption.id,
        "order_no": redemption.order_no,
        "status": redemption.status.value,
        "winner_name": winner.name,
        "winner_email": winner.email,
        "contact_name": redemption.contact_name,
        "contact_phone": redemption.contact_phone,
        "note": redemption.note,
        "items_summary": item_summary(items),
        "total_redeem_value": redemption.total_redeem_value,
        "quota": redemption.quota_snapshot,
        "unused_quota": redemption.quota_snapshot - redemption.total_redeem_value,
        "pickup_location": redemption.pickup_location_snapshot,
        "pickup_instructions": redemption.pickup_instructions_snapshot,
        "created_at": utc_iso(redemption.created_at),
        "picked_up_at": utc_iso(redemption.picked_up_at),
        "cancelled_at": utc_iso(redemption.cancelled_at),
    }
    if detail:
        result["items"] = [
            {
                "id": item.id,
                "prize_id": item.prize_id,
                "prize_name": item.prize_name_snapshot,
                "prize_image": item.prize_image_snapshot,
                "real_value": item.real_value_snapshot,
                "redeem_value": item.redeem_value_snapshot,
                "quantity": item.quantity,
                "line_redeem_value": item.line_redeem_value,
            }
            for item in items
        ]
    return result


@router.get("/events/{event_id}/redemptions")
def list_redemptions(
    event_id: int,
    db: DbSession,
    status: RedemptionStatus | None = None,
    search: str | None = Query(default=None, max_length=24),
) -> list[dict]:
    get_event_or_404(db, event_id)
    statement = select(Redemption).where(Redemption.event_id == event_id)
    if status is not None:
        statement = statement.where(Redemption.status == status)
    if search and search.strip():
        statement = statement.where(Redemption.order_no.like(f"%{search.strip()}%"))
    redemptions = db.scalars(statement.order_by(Redemption.created_at.desc(), Redemption.id.desc())).all()
    output = []
    for redemption in redemptions:
        _, winner, _, items = related(db, redemption)
        output.append(serialize_redemption(redemption, winner, items))
    return output


@router.get("/redemptions/{redemption_id}")
def get_redemption(redemption_id: int, db: DbSession) -> dict:
    redemption = redemption_or_404(db, redemption_id)
    _, winner, _, items = related(db, redemption)
    return serialize_redemption(redemption, winner, items, detail=True)


def transition(db: Session, redemption_id: int, *, expected: RedemptionStatus, target: RedemptionStatus, event_type: str, email_to_winner: bool) -> dict:
    try:
        redemption = redemption_or_404(db, redemption_id, lock=True)
        if redemption.status is not expected:
            fail(409, "invalid_redemption_transition", "当前兑换状态不允许此操作")
        code, winner, event, items = related(db, redemption)
        redemption.status = target
        if target is RedemptionStatus.PICKED_UP:
            redemption.picked_up_at = utc_now()
        rendered = render_template(template_text(db, event_type), status_context(redemption, code, winner, event, items))
        create_notification_pair(
            db,
            event_type=event_type,
            text_rendered=rendered,
            email_destination=winner.email if email_to_winner else get_settings().notification_email,
            winner_id=winner.id,
            redemption_id=redemption.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return serialize_redemption(redemption, winner, items, detail=True)


@router.post("/redemptions/{redemption_id}/ready")
def mark_ready(redemption_id: int, db: DbSession) -> dict:
    return transition(
        db,
        redemption_id,
        expected=RedemptionStatus.SUBMITTED,
        target=RedemptionStatus.READY,
        event_type="redemption_ready",
        email_to_winner=True,
    )


@router.post("/redemptions/{redemption_id}/pickup")
def mark_picked_up(redemption_id: int, db: DbSession) -> dict:
    return transition(
        db,
        redemption_id,
        expected=RedemptionStatus.READY,
        target=RedemptionStatus.PICKED_UP,
        event_type="redemption_picked_up",
        email_to_winner=False,
    )


@router.post("/redemptions/{redemption_id}/cancel")
def cancel_redemption(redemption_id: int, db: DbSession) -> dict:
    try:
        redemption = redemption_or_404(db, redemption_id, lock=True)
        if redemption.status not in (RedemptionStatus.SUBMITTED, RedemptionStatus.READY):
            fail(409, "invalid_redemption_transition", "当前兑换状态不能取消")
        code = db.scalar(
            select(RedemptionCode)
            .where(RedemptionCode.id == redemption.code_id)
            .with_for_update()
        )
        winner = db.get(Winner, code.winner_id) if code else None
        event = db.get(Event, redemption.event_id)
        items = list(
            db.scalars(
                select(RedemptionItem)
                .where(RedemptionItem.redemption_id == redemption.id)
                .order_by(RedemptionItem.prize_id)
            ).all()
        )
        prizes = list(
            db.scalars(
                select(Prize)
                .where(Prize.id.in_([item.prize_id for item in items]))
                .order_by(Prize.id)
                .with_for_update()
            ).all()
        )
        if code is None or winner is None or event is None or len(prizes) != len(items):
            fail(500, "invalid_redemption_data", "兑换记录关联数据不完整")
        quantities = {item.prize_id: item.quantity for item in items}
        for prize in prizes:
            prize.stock += quantities[prize.id]
        code.status = CodeStatus.ISSUED
        code.redeemed_at = None
        redemption.status = RedemptionStatus.CANCELLED
        redemption.cancelled_at = utc_now()
        rendered = render_template(
            template_text(db, "redemption_cancelled"),
            status_context(redemption, code, winner, event, items),
        )
        create_notification_pair(
            db,
            event_type="redemption_cancelled",
            text_rendered=rendered,
            email_destination=winner.email,
            winner_id=winner.id,
            redemption_id=redemption.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return serialize_redemption(redemption, winner, items, detail=True)


@router.get("/events/{event_id}/redemptions/export")
def export_redemptions(event_id: int, db: DbSession, format: str = Query(pattern="^(csv|xlsx)$")) -> Response:
    get_event_or_404(db, event_id)
    redemptions = db.scalars(
        select(Redemption).where(Redemption.event_id == event_id).order_by(Redemption.id)
    ).all()
    rows = []
    for redemption in redemptions:
        _, winner, _, items = related(db, redemption)
        for item in items:
            values = {
                "order_no": redemption.order_no,
                "status": redemption.status.value,
                "winner_name": winner.name,
                "winner_email": winner.email,
                "contact_name": redemption.contact_name,
                "contact_phone": redemption.contact_phone,
                "note": redemption.note or "",
                "quota": redemption.quota_snapshot,
                "total_redeem_value": redemption.total_redeem_value,
                "unused_quota": redemption.quota_snapshot - redemption.total_redeem_value,
                "prize_name": item.prize_name_snapshot,
                "real_value": f"{item.real_value_snapshot / 100:.2f}",
                "redeem_value": item.redeem_value_snapshot,
                "quantity": item.quantity,
                "line_redeem_value": item.line_redeem_value,
                "created_at": utc_iso(redemption.created_at),
                "picked_up_at": utc_iso(redemption.picked_up_at) or "",
                "cancelled_at": utc_iso(redemption.cancelled_at) or "",
            }
            rows.append([values[header] for header in EXPORT_HEADERS])
    if format == "csv":
        content, media_type = export_csv(EXPORT_HEADERS, rows), "text/csv; charset=utf-8"
    else:
        content, media_type = export_xlsx(EXPORT_HEADERS, rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="redemptions.{format}"'})
