import base64
import binascii
import io
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from PIL import Image, UnidentifiedImageError
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_redemptions import related, serialize_redemption, status_context
from .auth import require_admin_password
from .database import get_db
from .http import fail
from .models import CodeStatus, Redemption, RedemptionCode, RedemptionStatus, Winner
from .notifications import create_notification_jobs, render_notification, utc_now
from .schemas import StrictModel
from .spreadsheets import SIGNATURE_PREFIX, signature_png


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin_password)],
    tags=["admin-claims"],
)
DbSession = Annotated[Session, Depends(get_db)]
MAX_SIGNATURE_CHARS = 200_000
MAX_SIGNATURE_DIMENSION = 2000


class ClaimPickupRequest(StrictModel):
    code: Annotated[str, Field(min_length=4, max_length=64)]
    signature: Annotated[str, Field(min_length=32, max_length=MAX_SIGNATURE_CHARS + 64)]

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()


def normalize_code(value: str) -> str:
    return value.strip().upper()


def validate_signature(value: str) -> str:
    """Accept a trimmed mono PNG data URL produced by the claim tablet."""
    if not value.startswith(SIGNATURE_PREFIX):
        fail(422, "invalid_signature", "签名必须是 PNG data URL")
    payload = value[len(SIGNATURE_PREFIX):]
    if len(payload) > MAX_SIGNATURE_CHARS:
        fail(413, "signature_too_large", "签名图片过大")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        fail(422, "invalid_signature", "签名 base64 解码失败")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image.verify()
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != "PNG":
                fail(422, "invalid_signature", "签名必须是 PNG 图片")
            if image.width > MAX_SIGNATURE_DIMENSION or image.height > MAX_SIGNATURE_DIMENSION:
                fail(422, "invalid_signature", "签名图片尺寸过大")
    except (UnidentifiedImageError, OSError):
        fail(422, "invalid_signature", "签名不是有效的图片")
    return value


def claim_bundle(
    db: Session, code_value: str, *, lock: bool = False
) -> tuple[RedemptionCode, Winner, Redemption | None] | None:
    statement = (
        select(RedemptionCode, Winner)
        .join(Winner, RedemptionCode.winner_id == Winner.id)
        .where(RedemptionCode.code == code_value)
    )
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).one_or_none()
    if row is None:
        return None
    code, winner = row
    redemption_statement = select(Redemption).where(Redemption.code_id == code.id)
    if lock:
        redemption_statement = redemption_statement.with_for_update()
    redemption = db.scalar(redemption_statement)
    return code, winner, redemption


def claimability(code: RedemptionCode, redemption: Redemption | None) -> tuple[bool, str | None]:
    if code.status is CodeStatus.DISABLED:
        return False, "兑换码已撤销"
    if redemption is None:
        return False, "获奖人尚未提交兑换单"
    if redemption.status is RedemptionStatus.CANCELLED:
        return False, "兑换单已取消"
    if redemption.status is RedemptionStatus.PICKED_UP:
        return False, "已领取"
    return True, None


@router.get("/claims/lookup")
def lookup_claim(db: DbSession, code: str = Query(max_length=256)) -> dict:
    bundle = claim_bundle(db, normalize_code(code))
    if bundle is None:
        fail(404, "code_not_found", "兑换码不存在")
    code_record, winner, redemption = bundle
    claimable, reason = claimability(code_record, redemption)
    result = {
        "code": code_record.code,
        "winner": {
            "name": winner.name,
            "email": winner.email,
            "award_name": winner.award_name,
        },
        "redemption": None,
        "claimable": claimable,
        "reason": reason,
    }
    if redemption is not None:
        _, winner_row, _, items = related(db, redemption)
        result["redemption"] = serialize_redemption(redemption, winner_row, items)
    return result


@router.post("/claims/pickup")
def claim_pickup(db: DbSession, payload: ClaimPickupRequest) -> dict:
    validate_signature(payload.signature)
    try:
        bundle = claim_bundle(db, payload.code, lock=True)
        if bundle is None:
            fail(404, "code_not_found", "兑换码不存在")
        code, winner, redemption = bundle
        claimable, reason = claimability(code, redemption)
        if redemption is None:
            fail(404, "redemption_not_found", reason or "兑换记录不存在")
        if not claimable:
            fail(409, "not_claimable", reason or "当前状态不允许领奖")
        redemption.signature = payload.signature
        redemption.status = RedemptionStatus.PICKED_UP
        redemption.picked_up_at = utc_now()
        _, winner_row, event, items = related(db, redemption)
        rendered, html_rendered = render_notification(
            db, "redemption_picked_up", status_context(redemption, code, winner_row, event, items)
        )
        create_notification_jobs(
            db,
            event_type="redemption_picked_up",
            text_rendered=rendered,
            winner_email=winner_row.email,
            html_rendered=html_rendered,
            winner_id=winner_row.id,
            redemption_id=redemption.id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return serialize_redemption(redemption, winner_row, items, detail=True)
