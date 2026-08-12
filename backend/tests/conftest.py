import os
from pathlib import Path

import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


env_values = dotenv_values(Path(__file__).parents[2] / ".env")
main_url = str(env_values["DATABASE_URL"])
parsed_url = make_url(main_url)
test_url = parsed_url.set(database=f"{parsed_url.database}_test").render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = test_url
os.environ["ADMIN_PASSWORD"] = str(env_values["ADMIN_PASSWORD"])
os.environ["UPLOAD_DIR"] = str(env_values["UPLOAD_DIR"])

from app.models import (  # noqa: E402
    Event,
    NotificationJob,
    NotificationTemplate,
    Prize,
    Redemption,
    RedemptionCode,
    RedemptionItem,
    Winner,
)
from app.notifications import DEFAULT_TEMPLATES  # noqa: E402


test_engine = create_engine(test_url)


@pytest.fixture(autouse=True)
def clean_database():
    yield
    with Session(test_engine) as session:
        for model in (
            NotificationJob,
            RedemptionItem,
            Redemption,
            RedemptionCode,
            Winner,
            Prize,
            Event,
        ):
            session.execute(delete(model))
        for event_type, text_template in DEFAULT_TEMPLATES.items():
            template = session.scalar(
                select(NotificationTemplate).where(NotificationTemplate.event_type == event_type)
            )
            if template is None:
                session.add(NotificationTemplate(event_type=event_type, text_template=text_template))
            else:
                template.text_template = text_template
        session.commit()
