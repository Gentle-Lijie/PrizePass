from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    smtp_use_tls: bool = True
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
