from fastapi import APIRouter, Depends

from .auth import require_admin_password
from .admin_events import router as admin_events_router
from .admin_winners import router as admin_winners_router
from .public_redemption import router as public_redemption_router
from .admin_redemptions import router as admin_redemptions_router
from .admin_notifications import router as admin_notifications_router


router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/admin/check", dependencies=[Depends(require_admin_password)])
def admin_check() -> dict[str, bool]:
    return {"ok": True}


router.include_router(admin_events_router)
router.include_router(admin_winners_router)
router.include_router(public_redemption_router)
router.include_router(admin_redemptions_router)
router.include_router(admin_notifications_router)
