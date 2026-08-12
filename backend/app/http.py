from typing import NoReturn

from fastapi import HTTPException


def fail(status_code: int, code: str, message: str, details: dict | None = None) -> NoReturn:
    raise HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
    )
