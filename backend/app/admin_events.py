from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import require_admin_password
from .database import get_db
from .http import fail
from .models import Event, EventPrizeAvailability, EventStatus, Prize, Redemption, RedemptionItem, RedemptionStatus, Winner
from .schemas import (
    EventRead,
    EventWrite,
    PrizeRead,
    PrizeWrite,
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


# ============================================================
# Event-scoped prize availability management
# ============================================================


PRIZE_ORDER = (Prize.tag.is_(None), Prize.tag, Prize.id)


@router.get("/events/{event_id}/prizes", response_model=list[PrizeRead])
def list_event_prizes(event_id: int, db: DbSession) -> list[Prize]:
    """List prizes available for this specific event."""
    get_event_or_404(db, event_id)
    available_prize_ids = select(EventPrizeAvailability.prize_id).where(
        EventPrizeAvailability.event_id == event_id
    )
    return list(
        db.scalars(
            select(Prize)
            .where(Prize.id.in_(available_prize_ids))
            .order_by(*PRIZE_ORDER)
        ).all()
    )


@router.get("/events/{event_id}/prizes/summary")
def event_prize_summary(event_id: int, db: DbSession) -> dict[str, int]:
    """Prize totals scoped to this event's available prizes."""
    event = get_event_or_404(db, event_id)
    available_prize_ids = select(EventPrizeAvailability.prize_id).where(
        EventPrizeAvailability.event_id == event_id
    )
    available_value = db.scalar(
        select(func.coalesce(func.sum(Prize.real_value * func.greatest(Prize.stock, 0)), 0))
        .where(Prize.id.in_(available_prize_ids))
    ) or 0
    allocated_value = db.scalar(
        select(
            func.coalesce(
                func.sum(RedemptionItem.real_value_snapshot * RedemptionItem.quantity), 0
            )
        ).where(Redemption.status != RedemptionStatus.CANCELLED)
        .join(Redemption, Redemption.id == RedemptionItem.redemption_id)
        .where(Redemption.event_id == event_id)
    ) or 0
    claimed_value = db.scalar(
        select(
            func.coalesce(
                func.sum(RedemptionItem.real_value_snapshot * RedemptionItem.quantity), 0
            )
        ).where(Redemption.status == RedemptionStatus.PICKED_UP)
        .join(Redemption, Redemption.id == RedemptionItem.redemption_id)
        .where(Redemption.event_id == event_id)
    ) or 0
    return {
        "total_purchase_value": int(available_value + allocated_value),
        "claimed_purchase_value": int(claimed_value),
        "budget": event.budget,
    }


@router.post("/events/{event_id}/prizes/{prize_id}", status_code=201)
def add_prize_to_event(event_id: int, prize_id: int, db: DbSession) -> dict:
    """Make a prize from the global pool available for this event."""
    get_event_or_404(db, event_id)
    prize = db.get(Prize, prize_id)
    if prize is None:
        fail(404, "prize_not_found", "奖品不存在")
    existing = db.scalar(
        select(EventPrizeAvailability).where(
            EventPrizeAvailability.event_id == event_id,
            EventPrizeAvailability.prize_id == prize_id,
        )
    )
    if existing:
        return {"added": False, "message": "该奖品已对此比赛可用"}
    db.add(EventPrizeAvailability(event_id=event_id, prize_id=prize_id))
    db.commit()
    return {"added": True}


@router.delete("/events/{event_id}/prizes/{prize_id}", status_code=204)
def remove_prize_from_event(event_id: int, prize_id: int, db: DbSession):
    """Remove a prize from this event's availability (does not delete the prize)."""
    get_event_or_404(db, event_id)
    mapping = db.scalar(
        select(EventPrizeAvailability).where(
            EventPrizeAvailability.event_id == event_id,
            EventPrizeAvailability.prize_id == prize_id,
        )
    )
    if mapping is None:
        fail(404, "prize_not_available_for_event", "该奖品不在此比赛的可用列表中")
    db.delete(mapping)
    db.commit()


@router.get("/events/{event_id}/prizes/available")
def list_all_prizes_with_availability(event_id: int, db: DbSession) -> list[dict]:
    """List all prizes in the global pool with a flag indicating availability for this event."""
    get_event_or_404(db, event_id)
    all_prizes = list(db.scalars(select(Prize).order_by(*PRIZE_ORDER)).all())
    available_ids = set(
        db.scalars(
            select(EventPrizeAvailability.prize_id).where(
                EventPrizeAvailability.event_id == event_id
            )
        ).all()
    )
    return [
        {
            "id": prize.id,
            "name": prize.name,
            "image": prize.image,
            "jd_url": prize.jd_url,
            "real_value": prize.real_value,
            "purchase_value": prize.purchase_value,
            "redeem_value": prize.redeem_value,
            "stock": prize.stock,
            "description": prize.description,
            "tag": prize.tag,
            "is_active": prize.is_active,
            "available_for_event": prize.id in available_ids,
        }
        for prize in all_prizes
    ]
