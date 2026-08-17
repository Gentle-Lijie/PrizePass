import re
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .database import get_db
from .http import fail
from .models import (
    CodeStatus,
    Event,
    EventPrizeAvailability,
    EventStatus,
    Prize,
    Redemption,
    RedemptionCode,
    RedemptionItem,
    RedemptionStatus,
    Winner,
)
from .notifications import (
    create_notification_jobs,
    render_notification,
    utc_now,
    wish_submitted_context,
)
from .schemas import StrictModel, validate_https_url
from .timeutils import utc_iso


router = APIRouter(prefix="/public", tags=["public-redemption"])
DbSession = Annotated[Session, Depends(get_db)]
PHONE_RE = re.compile(r"^[0-9+()\-\s]{5,30}$")
ORDER_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class RedemptionRequestItem(StrictModel):
    prize_id: int
    quantity: Annotated[int, Field(gt=0, le=4_294_967_295)]


class RedemptionRequest(StrictModel):
    contact_name: Annotated[str, Field(min_length=1, max_length=100)]
    contact_phone: Annotated[str, Field(min_length=5, max_length=30)]
    note: Annotated[str | None, Field(max_length=500)] = None
    items: Annotated[list[RedemptionRequestItem], Field(min_length=0)] = []
    # Alternatively the winner may describe one custom prize instead of picking
    # catalog items; custom and items are mutually exclusive.
    custom_name: Annotated[str | None, Field(min_length=1, max_length=200)] = None
    custom_url: Annotated[str | None, Field(max_length=2000)] = None
    custom_note: Annotated[str | None, Field(max_length=2000)] = None
    custom_price: Annotated[int | None, Field(ge=0, le=4_294_967_295)] = None

    @field_validator("contact_name", "contact_phone")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("contact_phone")
    @classmethod
    def valid_phone(cls, value: str) -> str:
        if not PHONE_RE.fullmatch(value):
            raise ValueError("手机号只能包含数字、空格、+、- 和括号，长度为 5～30")
        return value

    @field_validator("note", "custom_note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("custom_name")
    @classmethod
    def normalize_custom_name(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("custom_url")
    @classmethod
    def valid_custom_url(cls, value: str | None) -> str | None:
        return validate_https_url(value)

    @model_validator(mode="after")
    def items_xor_custom(self) -> "RedemptionRequest":
        if self.custom_name and self.items:
            raise ValueError("自定义奖品不能与列表奖品同时提交")
        if not self.custom_name and not self.items:
            raise ValueError("请选择奖品或填写自定义奖品")
        return self


def now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def usable_code(db: Session, raw_code: str | None, *, lock: bool = False) -> tuple[RedemptionCode, Event, Winner]:
    value = (raw_code or "").strip().upper()
    if not value:
        fail(401, "invalid_redemption_code", "兑换码无效或当前不可使用")
    statement = select(RedemptionCode).where(RedemptionCode.code == value)
    if lock:
        statement = statement.with_for_update()
    code = db.scalar(statement)
    if code is None:
        fail(401 if not lock else 409, "invalid_redemption_code", "兑换码不存在，请检查后重试")
    if code.status is CodeStatus.REDEEMED:
        fail(409, "redemption_code_redeemed", "该兑换码已使用")
    if code.status is CodeStatus.DISABLED:
        fail(409, "redemption_code_disabled", "该兑换码已被撤销")
    event = db.get(Event, code.event_id)
    winner = db.get(Winner, code.winner_id)
    if event is None or winner is None:
        fail(409, "redemption_data_invalid", "兑换码关联数据不完整，请联系管理员")
    if event.status is EventStatus.DRAFT:
        fail(409, "event_not_active", "比赛尚未开放兑换，请稍后再试")
    if event.status is EventStatus.CLOSED:
        fail(409, "event_closed", "比赛兑换已关闭")
    if event.redemption_deadline <= now_utc_naive():
        fail(409, "redemption_expired", "该比赛已超过兑换截止时间")
    return code, event, winner


def code_header(x_redemption_code: str | None = Header(default=None)) -> str:
    return x_redemption_code or ""


@router.post("/code/verify")
def verify_code(db: DbSession, code_value: Annotated[str, Depends(code_header)]) -> dict:
    code, event, _ = usable_code(db, code_value)
    return {
        "event": {"id": event.id, "name": event.name, "redemption_deadline": utc_iso(event.redemption_deadline)},
        "quota": code.quota,
    }


@router.get("/redemption/context")
def redemption_context(db: DbSession, code_value: Annotated[str, Depends(code_header)]) -> dict:
    code, event, winner = usable_code(db, code_value)
    return {
        "event": {
            "id": event.id,
            "name": event.name,
            "description": event.description,
            "redemption_deadline": utc_iso(event.redemption_deadline),
            "pickup_location": event.pickup_location,
            "pickup_instructions": event.pickup_instructions,
        },
        "winner": {"name": winner.name, "email": winner.email},
        "quota": code.quota,
    }


@router.get("/redemption/prizes")
def redemption_prizes(db: DbSession, code_value: Annotated[str, Depends(code_header)]) -> list[dict]:
    code, event, _ = usable_code(db, code_value)
    # Show only prizes that are active AND available for this specific event.
    available_prize_ids = select(EventPrizeAvailability.prize_id).where(
        EventPrizeAvailability.event_id == event.id
    )
    prizes = db.scalars(
        select(Prize)
        .where(
            Prize.is_active == True,  # noqa: E712
            Prize.id.in_(available_prize_ids),
        )
        # Tagged prizes first ordered by tag text (numeric prefix controls section
        # order), untagged prizes fall into the trailing default section.
        .order_by(Prize.tag.is_(None), Prize.tag, Prize.id)
    ).all()
    return [
        {
            "id": prize.id,
            "name": prize.name,
            "image": prize.image,
            "jd_url": prize.jd_url,
            "purchase_value": prize.purchase_value,
            "redeem_value": prize.redeem_value,
            "description": prize.description,
            "tag": prize.tag,
        }
        for prize in prizes
    ]


def generate_order_no() -> str:
    timestamp = utc_now().strftime("%Y%m%d%H%M%S")
    suffix = "".join(secrets.choice(ORDER_ALPHABET) for _ in range(8))
    return f"PP{timestamp}{suffix}"


@router.post("/redemptions", status_code=201)
def submit_redemption(
    payload: RedemptionRequest,
    db: DbSession,
    code_value: Annotated[str, Depends(code_header)],
) -> dict:
    prize_ids = [item.prize_id for item in payload.items]
    if len(prize_ids) != len(set(prize_ids)):
        fail(422, "duplicate_prize", "购物篮中不能包含重复奖品")

    try:
        code, event, winner = usable_code(db, code_value, lock=True)
        existing_redemption = db.scalar(
            select(Redemption)
            .where(Redemption.code_id == code.id)
            .with_for_update()
        )
        if existing_redemption is not None and existing_redemption.status is not RedemptionStatus.CANCELLED:
            fail(409, "already_redeemed", "兑换码已提交过兑换")
        if payload.custom_name:
            prizes: list[Prize] = []
            quantities: dict[int, int] = {}
            total = 0
        else:
            quantities = {item.prize_id: item.quantity for item in payload.items}
            sorted_ids = sorted(prize_ids)
            prizes = list(
                db.scalars(
                    select(Prize)
                    .where(Prize.id.in_(sorted_ids))
                    .order_by(Prize.id)
                    .with_for_update()
                ).all()
            )
            if len(prizes) != len(sorted_ids) or any(not prize.is_active for prize in prizes):
                fail(409, "invalid_prize", "购物篮包含无效或已下架的奖品")
            # Validate that all selected prizes are available for this event.
            available_for_event = set(
                db.scalars(
                    select(EventPrizeAvailability.prize_id).where(
                        EventPrizeAvailability.event_id == event.id
                    )
                ).all()
            )
            if any(prize.id not in available_for_event for prize in prizes):
                fail(409, "prize_not_available_for_event", "购物篮包含对此比赛不可用的奖品")
            total = sum(prize.redeem_value * quantities[prize.id] for prize in prizes)
            if total > code.quota:
                fail(409, "quota_exceeded", "所选奖品总抵扣额度超过 quota")

        if existing_redemption is None:
            redemption = Redemption(
                order_no=generate_order_no(),
                event_id=event.id,
                code_id=code.id,
                contact_name=payload.contact_name,
                contact_phone=payload.contact_phone,
                note=payload.note,
                custom_name=payload.custom_name,
                custom_url=payload.custom_url,
                custom_note=payload.custom_note,
                custom_price=payload.custom_price,
                total_redeem_value=total,
                quota_snapshot=code.quota,
                pickup_location_snapshot=event.pickup_location,
                pickup_instructions_snapshot=event.pickup_instructions,
                status=RedemptionStatus.SUBMITTED,
            )
            db.add(redemption)
        else:
            old_items = db.scalars(
                select(RedemptionItem)
                .where(RedemptionItem.redemption_id == existing_redemption.id)
                .with_for_update()
            ).all()
            for old_item in old_items:
                db.delete(old_item)
            db.flush()
            redemption = existing_redemption
            redemption.order_no = generate_order_no()
            redemption.contact_name = payload.contact_name
            redemption.contact_phone = payload.contact_phone
            redemption.note = payload.note
            redemption.custom_name = payload.custom_name
            redemption.custom_url = payload.custom_url
            redemption.custom_note = payload.custom_note
            redemption.custom_price = payload.custom_price
            redemption.total_redeem_value = total
            redemption.quota_snapshot = code.quota
            redemption.pickup_location_snapshot = event.pickup_location
            redemption.pickup_instructions_snapshot = event.pickup_instructions
            redemption.status = RedemptionStatus.SUBMITTED
            redemption.created_at = utc_now()
            redemption.updated_at = utc_now()
            redemption.picked_up_at = None
            redemption.cancelled_at = None
        db.flush()
        summary_parts = []
        for prize in prizes:
            quantity = quantities[prize.id]
            line_value = prize.redeem_value * quantity
            db.add(
                RedemptionItem(
                    redemption_id=redemption.id,
                    prize_id=prize.id,
                    prize_name_snapshot=prize.name,
                    prize_image_snapshot=prize.image,
                    real_value_snapshot=prize.real_value,
                    purchase_value_snapshot=prize.purchase_value,
                    redeem_value_snapshot=prize.redeem_value,
                    quantity=quantity,
                    line_redeem_value=line_value,
                )
            )
            prize.stock -= quantity
            summary_parts.append(f"{prize.name} × {quantity}")
        code.status = CodeStatus.REDEEMED
        code.redeemed_at = utc_now()
        if payload.custom_name:
            rendered, html_rendered = render_notification(
                db, "wish_submitted", wish_submitted_context(winner, event, redemption.order_no, redemption)
            )
            create_notification_jobs(
                db,
                event_type="wish_submitted",
                text_rendered=rendered,
                winner_email=winner.email,
                html_rendered=html_rendered,
                winner_id=winner.id,
                redemption_id=redemption.id,
            )
        else:
            context = {
                "winner_name": winner.name,
                "winner_email": winner.email,
                "event_name": event.name,
                "code": code.code,
                "quota": code.quota,
                "redemption_url": f"{get_settings().public_base_url.rstrip('/')}/redeem",
                "deadline": event.redemption_deadline.isoformat(sep=" "),
                "order_no": redemption.order_no,
                "items_summary": "、".join(summary_parts),
                "total_redeem_value": total,
                "unused_quota": code.quota - total,
                "status": redemption.status.value,
                "pickup_location": event.pickup_location,
                "pickup_instructions": event.pickup_instructions,
            }
            rendered, html_rendered = render_notification(db, "redemption_submitted", context)
            create_notification_jobs(
                db,
                event_type="redemption_submitted",
                text_rendered=rendered,
                winner_email=winner.email,
                html_rendered=html_rendered,
                winner_id=winner.id,
                redemption_id=redemption.id,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "id": redemption.id,
        "order_no": redemption.order_no,
        "status": redemption.status.value,
        "total_redeem_value": total,
        "unused_quota": code.quota - total,
        "custom_name": redemption.custom_name,
        "pickup_location": redemption.pickup_location_snapshot,
        "pickup_instructions": redemption.pickup_instructions_snapshot,
    }
