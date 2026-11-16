from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    database_url: str = "mysql+pymysql://prizepass:prizepass@127.0.0.1:3306/prizepass"
    admin_password: str = ""
    public_base_url: str = "http://localhost:5177"
    app_port: int = 8007
    upload_dir: Path = Path("/var/lib/prizepass/uploads")

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = "PrizePass"
    # SMTP_SECURITY: none=明文, starttls=显式 TLS(587 常用), ssl=隐式 TLS/SMTPS(465 常用)
    smtp_security: Literal["none", "starttls", "ssl"] = "starttls"
    # 废弃：布尔旧开关，仅为迁移保留，等价于 SMTP_SECURITY=none/starttls
    smtp_use_tls: bool | None = None
    notification_email: str = ""
    webhook_url: str = ""

    # email-poster compatible HTTP relay.  Complex values are JSON objects in env vars.
    email_poster_post_url: str = ""
    email_poster_preset: str = "generic"
    email_poster_from_address: str = ""
    email_poster_headers: dict[str, str] = Field(default_factory=dict)
    email_poster_fields: dict[str, str] = Field(default_factory=dict)
    email_poster_extra: dict[str, object] = Field(default_factory=dict)

    worker_poll_seconds: float = Field(default=2.0, gt=0)

    @model_validator(mode="before")
    @classmethod
    def _migrate_smtp_use_tls(cls, values: Any) -> Any:
        """兼容旧开关 SMTP_USE_TLS：false → none，其余 → starttls；SMTP_SECURITY 优先。"""
        if isinstance(values, dict) and not values.get("smtp_security"):
            legacy = values.get("smtp_use_tls")
            if isinstance(legacy, str):
                legacy = legacy.strip().lower() in {"1", "true", "yes", "on"}
            if legacy is not None:
                values["smtp_security"] = "starttls" if legacy else "none"
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
