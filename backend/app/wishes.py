import shutil
from pathlib import Path

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Prize, PurchaseOrderItem, Redemption, Winner


# Wish-generated prizes carry no image of their own; they get this seeded
# placeholder until an admin uploads a real picture on the prize page.
PLACEHOLDER_IMAGE = "/uploads/prizes/placeholder.png"
WISH_PRIZE_TAG = "心愿奖品"
PRIZE_NAME_LIMIT = 200


def wish_prize_name(redemption: Redemption, winner: Winner | None) -> str:
    """Disambiguate same-named wishes by suffixing the winner's name."""
    suffix = f"（{winner.name}）" if winner else ""
    return f"{redemption.custom_name}{suffix}"[:PRIZE_NAME_LIMIT]


def wish_prize_description(redemption: Redemption, winner: Winner | None) -> str:
    parts = [f"心愿奖品，来源兑换单 {redemption.order_no}"]
    if winner is not None:
        parts.append(f"获奖人 {winner.name}")
    if redemption.custom_note:
        parts.append(f"备注：{redemption.custom_note}")
    return "；".join(parts)


def create_prize_from_wish(db: Session, redemption: Redemption, winner: Winner | None) -> tuple[Prize, bool]:
    """Idempotently materialize a wish redemption as a catalog Prize row.

    Returns (prize, created). If the wish was re-submitted after cancellation,
    an unreferenced prize is refreshed in place; a prize already tied to a
    purchase order keeps its original snapshot values.
    """
    existing = db.scalar(select(Prize).where(Prize.origin_redemption_id == redemption.id))
    if existing is not None:
        referenced = db.scalar(
            select(exists().where(PurchaseOrderItem.prize_id == existing.id))
        )
        if not referenced:
            existing.name = wish_prize_name(redemption, winner)
            existing.jd_url = redemption.custom_url
            existing.real_value = redemption.custom_price or 0
            existing.description = wish_prize_description(redemption, winner)
        return existing, False
    prize = Prize(
        name=wish_prize_name(redemption, winner),
        image=PLACEHOLDER_IMAGE,
        jd_url=redemption.custom_url,
        real_value=redemption.custom_price or 0,
        purchase_value=0,
        redeem_value=1,
        stock=0,
        description=wish_prize_description(redemption, winner),
        tag=WISH_PRIZE_TAG,
        is_active=False,
        origin_redemption_id=redemption.id,
    )
    db.add(prize)
    db.flush()
    return prize, True


def ensure_placeholder_image() -> None:
    """Copy the bundled placeholder into upload_dir so it is servable."""
    target = get_settings().upload_dir / "prizes" / "placeholder.png"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).parent / "assets" / "prize-placeholder.png", target)
