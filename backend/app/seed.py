from datetime import timedelta

from sqlalchemy import select

from .database import SessionLocal
from .models import Event, EventPrizeAvailability, EventStatus, Prize
from .notifications import utc_now


SEED_EVENT_NAME = "PrizePass 开发示例赛"


def seed() -> None:
    with SessionLocal.begin() as db:
        existing = db.scalar(select(Event).where(Event.name == SEED_EVENT_NAME))
        if existing is not None:
            print(f"开发种子已存在：event_id={existing.id}")
            return
        event = Event(
            name=SEED_EVENT_NAME,
            description="用于本地验证完整兑换流程的开发数据。",
            status=EventStatus.ACTIVE,
            redemption_deadline=utc_now() + timedelta(days=30),
            pickup_location="开发园区一层服务台",
            pickup_instructions="工作日 10:00–17:00，出示兑换单号领取。",
            budget=500_00,
        )
        db.add(event)
        db.flush()
        prizes = [
            Prize(
                name="保温杯",
                image="https://images.unsplash.com/photo-1602143407151-7111542de6e8",
                real_value=19900,
                purchase_value=19900,
                redeem_value=150,
                stock=20,
                description="黑色不锈钢保温杯",
            ),
            Prize(
                name="双肩背包",
                image="https://images.unsplash.com/photo-1553062407-98eeb64c6a62",
                real_value=29900,
                purchase_value=29900,
                redeem_value=250,
                stock=12,
                description="轻量日常双肩背包",
            ),
            Prize(
                name="机械键盘",
                image="https://images.unsplash.com/photo-1587829741301-dc798b83add3",
                real_value=49900,
                purchase_value=49900,
                redeem_value=400,
                stock=8,
                description="有线机械键盘",
            ),
        ]
        db.add_all(prizes)
        db.flush()
        # Make all prizes available for the seed event.
        for prize in prizes:
            db.add(EventPrizeAvailability(event_id=event.id, prize_id=prize.id))
        print(f"已创建开发种子：event_id={event.id}，prizes={len(prizes)}")


if __name__ == "__main__":
    seed()
