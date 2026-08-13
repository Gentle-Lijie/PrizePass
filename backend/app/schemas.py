from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from .models import EventStatus
from .timeutils import utc_iso


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def validate_image(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    if value.startswith("/uploads/prizes/") and "/" not in value[len("/uploads/prizes/") :]:
        return value
    raise ValueError("图片必须是 HTTPS URL 或已有的站内奖品图片路径")


def validate_https_url(value: str | None) -> str | None:
    value = value.strip() if value is not None else ""
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return value
    raise ValueError("京东链接必须是 HTTPS URL")


class EventWrite(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    description: str | None = None
    redemption_deadline: datetime
    pickup_location: Annotated[str, Field(min_length=1)]
    pickup_instructions: Annotated[str, Field(min_length=1)]
    budget: Annotated[int, Field(ge=0, le=4_294_967_295)] = 0
    status: EventStatus = EventStatus.DRAFT

    @field_validator("name", "pickup_location", "pickup_instructions")
    @classmethod
    def strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("字段不能为空")
        return value

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("redemption_deadline")
    @classmethod
    def normalize_deadline(cls, value: datetime) -> datetime:
        return utc_naive(value)


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    status: EventStatus
    redemption_deadline: datetime
    pickup_location: str
    pickup_instructions: str
    budget: int
    winner_count: int = 0
    redemption_count: int = 0
    created_at: datetime
    updated_at: datetime

    @field_serializer("redemption_deadline", "created_at", "updated_at")
    def serialize_datetimes(self, value: datetime) -> str:
        return utc_iso(value) or ""


class PrizeWrite(StrictModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    image: str
    jd_url: Annotated[str | None, Field(max_length=2000)] = None
    real_value: Annotated[int, Field(ge=0, le=4_294_967_295)]
    purchase_value: Annotated[int, Field(ge=0, le=4_294_967_295)] = 0
    redeem_value: Annotated[int, Field(gt=0, le=4_294_967_295)]
    stock: Annotated[int, Field(ge=-9_223_372_036_854_775_808, le=9_223_372_036_854_775_807)]
    description: Annotated[str | None, Field(max_length=5000)] = None

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名字不能为空")
        return value

    @field_validator("image")
    @classmethod
    def valid_image(cls, value: str) -> str:
        return validate_image(value)

    @field_validator("jd_url")
    @classmethod
    def valid_jd_url(cls, value: str | None) -> str | None:
        return validate_https_url(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class PrizeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    name: str
    image: str
    jd_url: str | None
    real_value: int
    purchase_value: int
    redeem_value: int
    stock: int
    description: str | None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def serialize_datetimes(self, value: datetime) -> str:
        return utc_iso(value) or ""
