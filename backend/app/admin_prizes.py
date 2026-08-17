from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .auth import require_admin_password
from .config import get_settings
from .database import get_db
from .http import fail
from .models import (
    EventPrizeAvailability,
    Prize,
    PurchaseOrder,
    PurchaseOrderStatus,
    Redemption,
    RedemptionItem,
    RedemptionStatus,
)
from .schemas import (
    PrizeBatchStock,
    PrizeBatchTag,
    PrizeBatchIds,
    PrizeRead,
    PrizeWrite,
)
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
    tags=["admin-prizes"],
)
DbSession = Annotated[Session, Depends(get_db)]

PRIZE_ORDER = (Prize.tag.is_(None), Prize.tag, Prize.id)


def get_prize_or_404(db: Session, prize_id: int) -> Prize:
    prize = db.get(Prize, prize_id)
    if prize is None:
        fail(404, "prize_not_found", "奖品不存在")
    return prize


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


STOCK_MIN = -9_223_372_036_854_775_808
STOCK_MAX = 9_223_372_036_854_775_807


def batch_prizes(db: Session, payload: PrizeBatchIds) -> list[Prize]:
    return list(
        db.scalars(
            select(Prize).where(Prize.id.in_(payload.ids)).order_by(*PRIZE_ORDER)
        ).all()
    )


def validate_prize_table(filename: str, content: bytes) -> dict:
    try:
        table = read_table(filename, content)
    except ValueError as exc:
        return {"valid": False, "rows": [], "errors": [{"row": 0, "field": "file", "message": str(exc)}]}
    errors: list[dict] = []
    normalized: list[dict] = []
    legacy_headers = ["name", "image", "real_value", "redeem_value", "stock", "description"]
    purchase_headers = ["name", "image", "real_value", "purchase_value", "redeem_value", "stock", "description"]
    if table.headers not in (PRIZE_HEADERS, PRIZE_HEADERS[:-1], purchase_headers, legacy_headers):
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
            "tag": lambda value: str(value).strip() if value is not None else "",
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


# ============================================================
# ROUTE ORDER MATTERS: all literal paths must be declared
# before the parameterized /prizes/{prize_id} route, otherwise
# FastAPI will parse "export" or "import" as a prize_id.
# ============================================================


@router.get("/prizes", response_model=list[PrizeRead])
def list_prizes(db: DbSession) -> list[Prize]:
    return list(db.scalars(select(Prize).order_by(*PRIZE_ORDER)).all())


@router.get("/prizes/summary")
def prize_summary(db: DbSession) -> dict[str, int]:
    """Pool-wide totals; the shared pool is no longer tied to a single event."""
    available_value = db.scalar(
        select(func.coalesce(func.sum(Prize.real_value * func.greatest(Prize.stock, 0)), 0))
    ) or 0
    allocated_value = db.scalar(
        select(
            func.coalesce(
                func.sum(RedemptionItem.real_value_snapshot * RedemptionItem.quantity), 0
            )
        ).where(Redemption.status != RedemptionStatus.CANCELLED)
        .join(Redemption, Redemption.id == RedemptionItem.redemption_id)
    ) or 0
    claimed_value = db.scalar(
        select(
            func.coalesce(
                func.sum(RedemptionItem.real_value_snapshot * RedemptionItem.quantity), 0
            )
        ).where(Redemption.status == RedemptionStatus.PICKED_UP)
        .join(Redemption, Redemption.id == RedemptionItem.redemption_id)
    ) or 0
    backorder_units = db.scalar(
        select(func.coalesce(func.sum(func.greatest(-Prize.stock, 0)), 0))
    ) or 0
    total_prizes = db.scalar(select(func.count(Prize.id))) or 0
    reimbursed_value = db.scalar(
        select(func.coalesce(func.sum(PurchaseOrder.total_value), 0)).where(
            PurchaseOrder.status == PurchaseOrderStatus.REIMBURSED
        )
    ) or 0
    return {
        "total_prizes": int(total_prizes),
        "backorder_units": int(backorder_units),
        "total_purchase_value": int(available_value + allocated_value),
        "claimed_purchase_value": int(claimed_value),
        "reimbursed_value": int(reimbursed_value),
    }


@router.get("/prizes/import/template")
def prize_template(format: str = Query(pattern="^(csv|xlsx)$")) -> Response:
    content, media_type = template_bytes(PRIZE_HEADERS, format)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="prizes-template.{format}"'})


@router.get("/prizes/export")
def export_prizes(db: DbSession, format: str = Query(pattern="^(csv|xlsx)$")) -> Response:
    prizes = list(db.scalars(select(Prize).order_by(*PRIZE_ORDER)).all())
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
            prize.tag or "",
        ]
        for prize in prizes
    ]
    if format == "csv":
        content, media_type = export_csv(PRIZE_HEADERS, rows), "text/csv; charset=utf-8"
    else:
        content, media_type = export_xlsx(PRIZE_HEADERS, rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="prizes.{format}"'})


@router.post("/prizes", response_model=PrizeRead, status_code=201)
def create_prize(payload: PrizeWrite, db: DbSession) -> Prize:
    prize = Prize(**payload.model_dump())
    db.add(prize)
    db.commit()
    db.refresh(prize)
    return prize


@router.post("/prizes/batch-tag")
def batch_set_prize_tag(payload: PrizeBatchTag, db: DbSession) -> dict:
    prizes = batch_prizes(db, payload)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for prize in prizes:
        prize.tag = payload.tag
        prize.updated_at = now
    db.commit()
    return {"updated": len(prizes)}


@router.post("/prizes/batch-stock")
def batch_adjust_prize_stock(payload: PrizeBatchStock, db: DbSession) -> dict:
    prizes = batch_prizes(db, payload)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for prize in prizes:
        stock = prize.stock + payload.value if payload.mode == "delta" else payload.value
        if not STOCK_MIN <= stock <= STOCK_MAX:
            fail(422, "stock_out_of_range", f"奖品“{prize.name}”的库存将超出允许范围")
        prize.stock = stock
        prize.updated_at = now
    db.commit()
    return {"updated": len(prizes)}


@router.post("/prizes/batch-delete")
def batch_delete_prizes(payload: PrizeBatchIds, db: DbSession) -> dict:
    prizes = batch_prizes(db, payload)
    referenced_ids = set(
        db.scalars(
            select(RedemptionItem.prize_id).where(RedemptionItem.prize_id.in_(payload.ids))
        ).all()
    )
    deletable = []
    skipped = []
    for prize in prizes:
        if prize.id in referenced_ids:
            skipped.append({"id": prize.id, "name": prize.name})
        else:
            deletable.append(prize)
    images = [prize.image for prize in deletable]
    ids = [prize.id for prize in deletable]
    # Delete event-prize availability records first (FK constraint).
    if ids:
        db.execute(
            delete(EventPrizeAvailability).where(EventPrizeAvailability.prize_id.in_(ids))
        )
    for prize in deletable:
        db.delete(prize)
    db.commit()
    for image, prize_id in zip(images, ids):
        maybe_remove_unreferenced_local_image(db, image, prize_id)
    return {"deleted": len(deletable), "skipped": skipped}


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


@router.post("/prizes/import/validate")
async def validate_prize_import(file: Annotated[UploadFile, File()]) -> dict:
    return validate_prize_table(file.filename or "", await file.read(MAX_FILE_SIZE + 1))


@router.post("/prizes/import/confirm", status_code=201)
async def confirm_prize_import(file: Annotated[UploadFile, File()], db: DbSession) -> dict:
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
        prize = Prize(**payload.model_dump())
        db.add(prize)
        prizes.append(prize)
    db.commit()
    return {"imported": len(prizes)}


# ============================================================
# Parameterized routes come LAST
# ============================================================


@router.get("/prizes/{prize_id}", response_model=PrizeRead)
def get_prize(prize_id: int, db: DbSession) -> Prize:
    return get_prize_or_404(db, prize_id)


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
    # Delete event-prize availability records first (FK constraint).
    db.execute(
        delete(EventPrizeAvailability).where(EventPrizeAvailability.prize_id == prize_id)
    )
    db.delete(prize)
    db.commit()
    maybe_remove_unreferenced_local_image(db, image, prize_id)
    return Response(status_code=204)
