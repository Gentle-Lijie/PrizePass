import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


def require_admin_password(x_admin_password: str | None = Header(default=None)) -> None:
    expected = get_settings().admin_password
    provided = x_admin_password or ""
    if not expected or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "管理员密码错误", "details": {}},
        )
