import io
import re
import secrets
import zipfile
from typing import Annotated, Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import require_admin_password
from .config import get_settings
from .database import get_db
from .http import fail
from .models import (
    Prize,
    PurchaseAttachmentKind,
    PurchaseOrder,
    PurchaseOrderAttachment,
    PurchaseOrderItem,
    PurchaseOrderStatus,
)
from .notifications import utc_now
from .schemas import StrictModel
from .spreadsheets import export_csv, export_xlsx
from .timeutils import utc_iso


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin_password)],
    tags=["admin-purchases"],
)
DbSession = Annotated[Session, Depends(get_db)]

MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_PDF_SIZE = 10 * 1024 * 1024
ORDER_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
EXPORT_HEADERS = [
    "order_no",
    "title",
    "status",
    "total_value",
    "items_summary",
    "attachment_count",
    "note",
    "created_at",
    "reimbursed_at",
    "cancelled_at",
]


class PurchaseItemWrite(StrictModel):
    prize_id: int
    quantity: Annotated[int, Field(gt=0, le=4_294_967_295)]


class PurchaseOrderWrite(StrictModel):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    note: Annotated[str | None, Field(max_length=2000)] = None
    items: Annotated[list[PurchaseItemWrite], Field(min_length=1, max_length=200)]

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


def generate_purchase_order_no() -> str:
    timestamp = utc_now().strftime("%Y%m%d%H%M%S")
    suffix = "".join(secrets.choice(ORDER_ALPHABET) for _ in range(6))
    return f"PO{timestamp}{suffix}"


def purchase_or_404(db: Session, purchase_id: int, *, lock: bool = False) -> PurchaseOrder:
    statement = select(PurchaseOrder).where(PurchaseOrder.id == purchase_id)
    if lock:
        statement = statement.with_for_update()
    order = db.scalar(statement)
    if order is None:
        fail(404, "purchase_order_not_found", "采购单不存在")
    return order


def require_draft(order: PurchaseOrder) -> None:
    if order.status is not PurchaseOrderStatus.DRAFT:
        fail(409, "purchase_order_not_draft", "只有草稿状态的采购单可以修改")


def order_items(db: Session, order_id: int) -> list[PurchaseOrderItem]:
    return list(
        db.scalars(
            select(PurchaseOrderItem)
            .where(PurchaseOrderItem.purchase_order_id == order_id)
            .order_by(PurchaseOrderItem.id)
        ).all()
    )


def order_attachments(db: Session, order_id: int) -> list[PurchaseOrderAttachment]:
    return list(
        db.scalars(
            select(PurchaseOrderAttachment)
            .where(PurchaseOrderAttachment.purchase_order_id == order_id)
            .order_by(PurchaseOrderAttachment.id)
        ).all()
    )


def items_summary(items: list[PurchaseOrderItem]) -> str:
    return "、".join(f"{item.prize_name_snapshot} × {item.quantity}" for item in items)


def serialize_purchase(
    order: PurchaseOrder,
    items: list[PurchaseOrderItem],
    attachments: list[PurchaseOrderAttachment],
    *,
    detail: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": order.id,
        "order_no": order.order_no,
        "title": order.title,
        "note": order.note,
        "status": order.status.value,
        "total_value": order.total_value,
        "items_summary": items_summary(items),
        "item_count": len(items),
        "attachment_count": len(attachments),
        "created_at": utc_iso(order.created_at),
        "reimbursed_at": utc_iso(order.reimbursed_at),
        "cancelled_at": utc_iso(order.cancelled_at),
    }
    if detail:
        result["items"] = [
            {
                "id": item.id,
                "prize_id": item.prize_id,
                "prize_name": item.prize_name_snapshot,
                "unit_value": item.unit_value_snapshot,
                "quantity": item.quantity,
                "line_value": item.line_value,
            }
            for item in items
        ]
        result["attachments"] = [
            {
                "id": attachment.id,
                "kind": attachment.kind.value,
                "filename": attachment.filename,
                "byte_size": attachment.byte_size,
                "created_at": utc_iso(attachment.created_at),
            }
            for attachment in attachments
        ]
    return result


def replace_items(db: Session, order: PurchaseOrder, payload: PurchaseOrderWrite) -> int:
    """Snapshot matched prizes into order items; caller commits. Returns total cents."""
    quantities = {item.prize_id: item.quantity for item in payload.items}
    if len(quantities) != len(payload.items):
        fail(422, "duplicate_prize", "采购单包含重复奖品")
    prizes = list(
        db.scalars(
            select(Prize).where(Prize.id.in_(sorted(quantities))).order_by(Prize.id).with_for_update()
        ).all()
    )
    if len(prizes) != len(quantities):
        fail(409, "invalid_prize", "采购单包含不存在的奖品")
    for item in order_items(db, order.id):
        db.delete(item)
    db.flush()
    total = 0
    for prize in prizes:
        quantity = quantities[prize.id]
        line_value = prize.real_value * quantity
        db.add(
            PurchaseOrderItem(
                purchase_order_id=order.id,
                prize_id=prize.id,
                prize_name_snapshot=prize.name,
                unit_value_snapshot=prize.real_value,
                quantity=quantity,
                line_value=line_value,
            )
        )
        total += line_value
    order.total_value = total
    return total


@router.get("/purchases")
def list_purchases(
    db: DbSession, status: PurchaseOrderStatus | None = None
) -> list[dict[str, Any]]:
    statement = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
    if status is not None:
        statement = statement.where(PurchaseOrder.status == status)
    orders = list(db.scalars(statement).all())
    return [
        serialize_purchase(order, order_items(db, order.id), order_attachments(db, order.id))
        for order in orders
    ]


@router.get("/purchases/export")
def export_purchases(db: DbSession, format: str = Query(pattern="^(csv|xlsx)$")) -> Response:
    orders = list(
        db.scalars(
            select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
        ).all()
    )
    rows = []
    for order in orders:
        items = order_items(db, order.id)
        values = {
            "order_no": order.order_no,
            "title": order.title,
            "status": order.status.value,
            "total_value": f"{order.total_value / 100:.2f}",
            "items_summary": items_summary(items),
            "attachment_count": len(order_attachments(db, order.id)),
            "note": order.note or "",
            "created_at": utc_iso(order.created_at),
            "reimbursed_at": utc_iso(order.reimbursed_at) or "",
            "cancelled_at": utc_iso(order.cancelled_at) or "",
        }
        rows.append([values[header] for header in EXPORT_HEADERS])
    if format == "csv":
        content, media_type = export_csv(EXPORT_HEADERS, rows), "text/csv; charset=utf-8"
    else:
        content, media_type = export_xlsx(EXPORT_HEADERS, rows), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="purchases.{format}"'})


@router.post("/purchases", status_code=201)
def create_purchase(payload: PurchaseOrderWrite, db: DbSession) -> dict[str, Any]:
    order = PurchaseOrder(
        order_no=generate_purchase_order_no(),
        title=payload.title,
        note=payload.note,
        status=PurchaseOrderStatus.DRAFT,
    )
    db.add(order)
    db.flush()
    replace_items(db, order, payload)
    db.commit()
    db.refresh(order)
    return serialize_purchase(order, order_items(db, order.id), [], detail=True)


@router.get("/purchases/{purchase_id}")
def get_purchase(purchase_id: int, db: DbSession) -> dict[str, Any]:
    order = purchase_or_404(db, purchase_id)
    return serialize_purchase(order, order_items(db, order.id), order_attachments(db, order.id), detail=True)


@router.put("/purchases/{purchase_id}")
def update_purchase(purchase_id: int, payload: PurchaseOrderWrite, db: DbSession) -> dict[str, Any]:
    order = purchase_or_404(db, purchase_id, lock=True)
    require_draft(order)
    order.title = payload.title
    order.note = payload.note
    replace_items(db, order, payload)
    db.commit()
    db.refresh(order)
    return serialize_purchase(order, order_items(db, order.id), order_attachments(db, order.id), detail=True)


def remove_attachment_files(attachments: list[PurchaseOrderAttachment]) -> None:
    upload_dir = get_settings().upload_dir
    for attachment in attachments:
        path = upload_dir / attachment.storage_path
        if path.is_file():
            path.unlink()


@router.delete("/purchases/{purchase_id}", status_code=204)
def delete_purchase(purchase_id: int, db: DbSession) -> Response:
    order = purchase_or_404(db, purchase_id, lock=True)
    if order.status is PurchaseOrderStatus.REIMBURSED:
        fail(409, "purchase_order_reimbursed", "已报销的采购单不能删除，需保留财务记录")
    attachments = order_attachments(db, order.id)
    for item in order_items(db, order.id):
        db.delete(item)
    for attachment in attachments:
        db.delete(attachment)
    # 子表只配置了外键、没有 relationship，flush 顺序不会自动先删子表，
    # 必须先 flush 子表删除，再删主表，否则触发外键约束。
    db.flush()
    db.delete(order)
    db.commit()
    remove_attachment_files(attachments)
    return Response(status_code=204)


FILENAME_SAFE_RE = re.compile(r"[^\w.\-]+")
IMAGE_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def safe_filename(filename: str) -> str:
    cleaned = FILENAME_SAFE_RE.sub("_", filename).strip("._") or "file"
    return cleaned[:150]


def validate_attachment(kind: PurchaseAttachmentKind, filename: str, content: bytes) -> str:
    """Validate content by kind and return the stored extension."""
    if kind is PurchaseAttachmentKind.TRANSACTION_SCREENSHOT:
        if len(content) > MAX_IMAGE_SIZE:
            fail(413, "image_too_large", "交易截图不能超过 5 MB")
        try:
            with Image.open(io.BytesIO(content)) as image:
                image.verify()
                image_format = image.format
        except (UnidentifiedImageError, OSError):
            fail(422, "invalid_image", "交易截图必须是有效的 JPEG、PNG 或 WebP 图片")
        if image_format not in IMAGE_EXTENSIONS:
            fail(422, "invalid_image_type", "交易截图只支持 JPEG、PNG 或 WebP 图片")
        return IMAGE_EXTENSIONS[image_format]
    if len(content) > MAX_PDF_SIZE:
        fail(413, "pdf_too_large", "发票 PDF 不能超过 10 MB")
    if not content.startswith(b"%PDF-"):
        fail(422, "invalid_pdf", "发票必须是有效的 PDF 文件")
    return "pdf"


@router.post("/purchases/{purchase_id}/attachments", status_code=201)
async def upload_attachment(
    purchase_id: int,
    db: DbSession,
    kind: Annotated[PurchaseAttachmentKind, Form()],
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    order = purchase_or_404(db, purchase_id, lock=True)
    require_draft(order)
    limit = MAX_PDF_SIZE if kind is PurchaseAttachmentKind.INVOICE_PDF else MAX_IMAGE_SIZE
    content = await file.read(limit + 1)
    extension = validate_attachment(kind, file.filename or "", content)
    original_name = safe_filename(file.filename or f"attachment.{extension}")
    purchase_dir = get_settings().upload_dir / "purchases"
    purchase_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid4().hex}.{extension}"
    (purchase_dir / stored_name).write_bytes(content)
    attachment = PurchaseOrderAttachment(
        purchase_order_id=order.id,
        kind=kind,
        filename=original_name,
        storage_path=f"purchases/{stored_name}",
        byte_size=len(content),
    )
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return {
        "id": attachment.id,
        "kind": attachment.kind.value,
        "filename": attachment.filename,
        "byte_size": attachment.byte_size,
        "created_at": utc_iso(attachment.created_at),
    }


@router.delete("/purchases/{purchase_id}/attachments/{attachment_id}", status_code=204)
def delete_attachment(purchase_id: int, attachment_id: int, db: DbSession) -> Response:
    order = purchase_or_404(db, purchase_id, lock=True)
    require_draft(order)
    attachment = db.get(PurchaseOrderAttachment, attachment_id)
    if attachment is None or attachment.purchase_order_id != order.id:
        fail(404, "attachment_not_found", "附件不存在")
    db.delete(attachment)
    db.commit()
    remove_attachment_files([attachment])
    return Response(status_code=204)


@router.post("/purchases/{purchase_id}/reimburse")
def reimburse_purchase(purchase_id: int, db: DbSession) -> dict[str, Any]:
    order = purchase_or_404(db, purchase_id, lock=True)
    require_draft(order)
    attachments = order_attachments(db, order.id)
    kinds = {attachment.kind for attachment in attachments}
    if PurchaseAttachmentKind.TRANSACTION_SCREENSHOT not in kinds:
        fail(409, "missing_transaction_screenshot", "标记报销前请先上传交易截图")
    if PurchaseAttachmentKind.INVOICE_PDF not in kinds:
        fail(409, "missing_invoice_pdf", "标记报销前请先上传发票 PDF")
    order.status = PurchaseOrderStatus.REIMBURSED
    order.reimbursed_at = utc_now()
    db.commit()
    db.refresh(order)
    return serialize_purchase(order, order_items(db, order.id), attachments, detail=True)


@router.post("/purchases/{purchase_id}/cancel")
def cancel_purchase(purchase_id: int, db: DbSession) -> dict[str, Any]:
    order = purchase_or_404(db, purchase_id, lock=True)
    require_draft(order)
    order.status = PurchaseOrderStatus.CANCELLED
    order.cancelled_at = utc_now()
    db.commit()
    db.refresh(order)
    return serialize_purchase(order, order_items(db, order.id), order_attachments(db, order.id), detail=True)


MANIFEST_HEADERS = [
    "order_no",
    "title",
    "status",
    "prize_name",
    "unit_value",
    "quantity",
    "line_value",
    "total_value",
    "note",
    "created_at",
    "reimbursed_at",
]


@router.get("/purchases/{purchase_id}/package")
def download_package(purchase_id: int, db: DbSession) -> Response:
    order = purchase_or_404(db, purchase_id)
    items = order_items(db, order.id)
    attachments = order_attachments(db, order.id)
    manifest_rows = [
        [
            order.order_no,
            order.title,
            order.status.value,
            item.prize_name_snapshot,
            f"{item.unit_value_snapshot / 100:.2f}",
            item.quantity,
            f"{item.line_value / 100:.2f}",
            f"{order.total_value / 100:.2f}",
            order.note or "",
            utc_iso(order.created_at) or "",
            utc_iso(order.reimbursed_at) or "",
        ]
        for item in items
    ] or [
        [
            order.order_no,
            order.title,
            order.status.value,
            "",
            "",
            "",
            "",
            f"{order.total_value / 100:.2f}",
            order.note or "",
            utc_iso(order.created_at) or "",
            utc_iso(order.reimbursed_at) or "",
        ]
    ]
    manifest = export_xlsx(MANIFEST_HEADERS, manifest_rows)
    upload_dir = get_settings().upload_dir
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(f"{order.order_no}/manifest.xlsx", manifest)
        for attachment in attachments:
            path = upload_dir / attachment.storage_path
            if path.is_file():
                archive.write(path, f"{order.order_no}/attachments/{attachment.filename}")
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{order.order_no}.zip"'},
    )
