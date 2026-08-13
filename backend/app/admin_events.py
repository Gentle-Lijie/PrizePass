from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import require_admin_password
from .config import get_settings
from .database import get_db
from .http import fail
from .models import Event, EventStatus, Prize, Redemption, RedemptionItem, RedemptionStatus, Winner
from .schemas import EventRead, EventWrite, PrizeRead, PrizeWrite
from .spreadsheets import (
    MAX_FILE_SIZE,
    PRIZE_HEADERS,
    export_csv,
    export_xlsx,
    parse_money_to_cents,
    parse_nonnegative_integer,
    parse_positive_integer,
    read_table,
    template_bytes,
)


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin_password)],
    tags=["admin"],
)
DbSession = Annotated[Session, Depends(get_db)]


def get_event_or_404(db: Session, event_id: int) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        fail(404, "event_not_found", "比赛不存在")
    return event


def maybe_open_event(event: Event) -> None:
    """草稿比赛在有获奖人/兑换码后自动开放兑换；active 保持，closed 不自动重开。"""
    if event.status is EventStatus.DRAFT:
        event.status = EventStatus.ACTIVE


def get_prize_or_404(db: Session, prize_id: int) -> Prize:
    prize = db.get(Prize, prize_id)
    if prize is None:
        fail(404, "prize_not_found", "奖品不存在")
    return prize


def event_read(event: Event, winner_count: int = 0, redemption_count: int = 0) -> EventRead:
    return EventRead.model_validate(event).model_copy(
        update={"winner_count": winner_count, "redemption_count": redemption_count}
    )


@router.get("/events", response_model=list[EventRead])
def list_events(db: DbSession) -> list[EventRead]:
    winner_count = (
        select(func.count(Winner.id)).where(Winner.event_id == Event.id).correlate(Event).scalar_subquery()
    )
    redemption_count = (
        select(func.count(Redemption.id))
        .where(Redemption.event_id == Event.id)
        .correlate(Event)
        .scalar_subquery()
    )
    rows = db.execute(
        select(Event, winner_count.label("winner_count"), redemption_count.label("redemption_count"))
        .order_by(Event.created_at.desc())
    ).all()
    return [event_read(event, winners, redemptions) for event, winners, redemptions in rows]


@router.post("/events", response_model=EventRead, status_code=201)
def create_event(payload: EventWrite, db: DbSession) -> EventRead:
    if payload.status is not EventStatus.DRAFT:
        fail(422, "invalid_initial_status", "新比赛必须为草稿状态")
    event = Event(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event_read(event)


@router.get("/events/{event_id}", response_model=EventRead)
def get_event(event_id: int, db: DbSession) -> EventRead:
    event = get_event_or_404(db, event_id)
    winners = db.scalar(select(func.count(Winner.id)).where(Winner.event_id == event_id)) or 0
    redemptions = db.scalar(select(func.count(Redemption.id)).where(Redemption.event_id == event_id)) or 0
    return event_read(event, winners, redemptions)


@router.put("/events/{event_id}", response_model=EventRead)
def update_event(event_id: int, payload: EventWrite, db: DbSession) -> EventRead:
    event = get_event_or_404(db, event_id)
    allowed = {
        EventStatus.DRAFT: {EventStatus.DRAFT, EventStatus.ACTIVE},
        EventStatus.ACTIVE: {EventStatus.ACTIVE, EventStatus.CLOSED},
        EventStatus.CLOSED: {EventStatus.CLOSED, EventStatus.ACTIVE},
    }
    if payload.status not in allowed[event.status]:
        fail(409, "invalid_event_transition", "比赛状态变化不允许")
    for field, value in payload.model_dump().items():
        setattr(event, field, value)
    event.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(event)
    return get_event(event_id, db)


@router.get("/events/{event_id}/prizes", response_model=list[PrizeRead])
def list_prizes(event_id: int, db: DbSession) -> list[Prize]:
    get_event_or_404(db, event_id)
    return list(db.scalars(select(Prize).where(Prize.event_id == event_id).order_by(Prize.id)).all())


@router.get("/events/{event_id}/prizes/summary")
def prize_summary(event_id: int, db: DbSession) -> dict[str, int]:
    event = get_event_or_404(db, event_id)
    available_value = db.scalar(
        select(
            func.coalesce(
                func.sum(Prize.real_value * func.greatest(Prize.stock, 0)), 0
            )
        ).where(
            Prize.event_id == event_id
        )
    ) or 0
    allocated_value = db.scalar(
        select(
            func.coalesce(
                func.sum(RedemptionItem.real_value_snapshot * RedemptionItem.quantity), 0
            )
        )
        .join(Redemption, Redemption.id == RedemptionItem.redemption_id)
        .where(
            Redemption.event_id == event_id,
            Redemption.status != RedemptionStatus.CANCELLED,
        )
    ) or 0
    claimed_value = db.scalar(
        select(
            func.coalesce(
                func.sum(RedemptionItem.real_value_snapshot * RedemptionItem.quantity), 0
            )
        )
        .join(Redemption, Redemption.id == RedemptionItem.redemption_id)
        .where(
            Redemption.event_id == event_id,
            Redemption.status == RedemptionStatus.PICKED_UP,
        )
    ) or 0
    return {
        "total_purchase_value": int(available_value + allocated_value),
        "claimed_purchase_value": int(claimed_value),
        "budget": event.budget,
    }


@router.post("/events/{event_id}/prizes", response_model=PrizeRead, status_code=201)
def create_prize(event_id: int, payload: PrizeWrite, db: DbSession) -> Prize:
    get_event_or_404(db, event_id)
    prize = Prize(event_id=event_id, **payload.model_dump())
    db.add(prize)
    db.commit()
    db.refresh(prize)
    return prize


@router.get("/prizes/{prize_id}", response_model=PrizeRead)
def get_prize(prize_id: int, db: DbSession) -> Prize:
    return get_prize_or_404(db, prize_id)


def maybe_remove_unreferenced_local_image(db: Session, image: str, excluded_prize_id: int) -> None:
    if not image.startswith("/uploads/prizes/"):
        return
    used_by_prize = db.scalar(
        select(func.count(Prize.id)).where(Prize.image == image, Prize.id != excluded_prize_id)
    )
    used_by_snapshot = db.scalar(
        select(func.count(RedemptionItem.id)).where(RedemptionItem.prize_image_snapshot == image)
    )
    if used_by_prize or used_by_snapshot:
        return
    filename = image.removeprefix("/uploads/prizes/")
    path = get_settings().upload_dir / "prizes" / filename
    if path.is_file():
        path.unlink()


@router.put("/prizes/{prize_id}", response_model=PrizeRead)
def update_prize(prize_id: int, payload: PrizeWrite, db: DbSession) -> Prize:
    prize = get_prize_or_404(db, prize_id)
    old_image = prize.image
    for field, value in payload.model_dump().items():
        setattr(prize, field, value)
    prize.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    db.refresh(prize)
    if old_image != prize.image:
        maybe_remove_unreferenced_local_image(db, old_image, prize.id)
    return prize


@router.delete("/prizes/{prize_id}", status_code=204)
def delete_prize(prize_id: int, db: DbSession) -> Response:
    prize = get_prize_or_404(db, prize_id)
    referenced = db.scalar(
        select(func.count(RedemptionItem.id)).where(RedemptionItem.prize_id == prize_id)
    )
    if referenced:
        fail(409, "prize_in_use", "奖品已被兑换记录引用，不能删除")
    image = prize.image
    db.delete(prize)
    db.commit()
    maybe_remove_unreferenced_local_image(db, image, prize_id)
    return Response(status_code=204)


@router.post("/uploads/prize-image", status_code=201)
async def upload_prize_image(file: Annotated[UploadFile, File()]) -> dict[str, str]:
    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        fail(413, "image_too_large", "图片不能超过 5 MB")
    import io

    try:
        with Image.open(io.BytesIO(content)) as image:
            image.verify()
            image_format = image.format
    except (UnidentifiedImageError, OSError):
        fail(422, "invalid_image", "文件不是有效的 JPEG、PNG 或 WebP 图片")
    extensions = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
    if image_format not in extensions:
        fail(422, "invalid_image_type", "只支持 JPEG、PNG 或 WebP 图片")
    prize_dir = get_settings().upload_dir / "prizes"
    prize_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}.{extensions[image_format]}"
    path = prize_dir / filename
    path.write_bytes(content)
    return {"image": f"/uploads/prizes/{filename}"}


def validate_prize_table(filename: str, content: bytes) -> dict:
    try:
        table = read_table(filename, content)
    except ValueError as exc:
        return {"valid": False, "rows": [], "errors": [{"row": 0, "field": "file", "message": str(exc)}]}
    errors: list[dict] = []
    normalized: list[dict] = []
    legacy_headers = ["name", "image", "real_value", "redeem_value", "stock", "description"]
    purchase_headers = ["name", "image", "real_value", "purchase_value", "redeem_value", "stock", "description"]
    if table.headers not in (PRIZE_HEADERS, purchase_headers, legacy_headers):
        return {
            "valid": False,
            "rows": [],
            "errors": [{"row": 1, "field": "header", "message": f"表头必须为 {','.join(PRIZE_HEADERS)}"}],
        }
    for index, raw in enumerate(table.rows, start=2):
        if len(raw) > len(PRIZE_HEADERS):
            errors.append({"row": index, "field": "row", "message": "该行包含多余列"})
        values = list(raw) + [None] * (len(table.headers) - len(raw))
        source = dict(zip(table.headers, values[: len(table.headers)], strict=True))
        row: dict = {}
        field_parsers = {
            "name": lambda value: str(value).strip() if value is not None else "",
            "image": lambda value: str(value).strip() if value is not None else "",
            "jd_url": lambda value: str(value).strip() if value is not None else "",
            "real_value": parse_money_to_cents,
            "purchase_value": lambda value: parse_money_to_cents(value, "展示价格"),
            "redeem_value": lambda value: parse_positive_integer(value, "抵扣价值"),
            "stock": lambda value: parse_nonnegative_integer(value, "库存"),
            "description": lambda value: str(value).strip() if value is not None else "",
        }
        for column, parser in field_parsers.items():
            try:
                default = "0" if column == "purchase_value" else None
                row[column] = parser(source.get(column, default))
            except ValueError as exc:
                errors.append({"row": index, "field": column, "message": str(exc)})
        if not row.get("name"):
            errors.append({"row": index, "field": "name", "message": "名字不能为空"})
        elif len(row["name"]) > 200:
            errors.append({"row": index, "field": "name", "message": "名字不能超过 200 字符"})
        try:
            PrizeWrite(**row)
        except Exception as exc:
            for issue in getattr(exc, "errors", lambda: [])():
                field = str(issue.get("loc", ["row"])[-1])
                if not any(error["row"] == index and error["field"] == field for error in errors):
                    errors.append({"row": index, "field": field, "message": issue["msg"]})
        row["real_value"] = f"{row.get('real_value', 0) / 100:.2f}"
        row["purchase_value"] = f"{row.get('purchase_value', 0) / 100:.2f}"
        normalized.append(row)
    return {"valid": not errors, "rows": normalized, "errors": errors, "count": len(normalized)}


@router.get("/events/{event_id}/prizes/import/template")
def prize_template(event_id: int, db: DbSession, format: str = Query(pattern="^(csv|xlsx)$")) -> Response:
    get_event_or_404(db, event_id)
    content, media_type = template_bytes(PRIZE_HEADERS, format)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="prizes-template.{format}"'})


@router.post("/events/{event_id}/prizes/import/validate")
async def validate_prize_import(event_id: int, db: DbSession, file: Annotated[UploadFile, File()]) -> dict:
    get_event_or_404(db, event_id)
    return validate_prize_table(file.filename or "", await file.read(MAX_FILE_SIZE + 1))


@router.post("/events/{event_id}/prizes/import/confirm", status_code=201)
async def confirm_prize_import(event_id: int, db: DbSession, file: Annotated[UploadFile, File()]) -> dict:
    get_event_or_404(db, event_id)
    result = validate_prize_table(file.filename or "", await file.read(MAX_FILE_SIZE + 1))
    if not result["valid"]:
        fail(422, "invalid_import", "表格存在错误，未导入任何奖品", {"errors": result["errors"]})
    prizes = []
    for row in result["rows"]:
        payload = PrizeWrite(
            **{
                **row,
                "real_value": parse_money_to_cents(row["real_value"]),
                "purchase_value": parse_money_to_cents(row["purchase_value"], "展示价格"),
                "description": row["description"] or None,
            }
        )
        prize = Prize(event_id=event_id, **payload.model_dump())
        db.add(prize)
        prizes.append(prize)
    db.commit()
    return {"imported": len(prizes)}


@router.get("/events/{event_id}/prizes/export")
def export_prizes(event_id: int, db: DbSession, format: str = Query(pattern="^(csv|xlsx)$")) -> Response:
    prizes = list(db.scalars(select(Prize).where(Prize.event_id == event_id).order_by(Prize.id)).all())
    get_event_or_404(db, event_id)
    rows = [
        [
            prize.name,
            prize.image,
            f"{prize.real_value / 100:.2f}",
            f"{prize.purchase_value / 100:.2f}",
            prize.redeem_value,
            prize.stock,
            prize.description or "",
            prize.jd_url or "",
        ]
        for prize in prizes
    ]
    if format == "csv":
        content, media_type = export_csv(PRIZE_HEADERS, rows), "text/csv; charset=utf-8"
    else:
        content, media_type = export_xlsx(PRIZE_HEADERS, rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="prizes.{format}"'})
