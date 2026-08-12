from datetime import datetime


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat() + "Z"
