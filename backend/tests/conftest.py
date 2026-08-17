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
os.environ["ADMIN_PASSWORD"] = "prizepass-dev-admin"
os.environ["UPLOAD_DIR"] = str(env_values["UPLOAD_DIR"])
os.environ["EMAIL_POSTER_POST_URL"] = ""

from app.models import (  # noqa: E402
    Event,
    EventPrizeAvailability,
    NotificationJob,
    NotificationRoutingRule,
    NotificationTemplate,
    Prize,
    PurchaseOrder,
    PurchaseOrderAttachment,
    PurchaseOrderItem,
    Redemption,
    RedemptionCode,
    RedemptionItem,
    Winner,
)
from app.notifications import (  # noqa: E402
    DEFAULT_HTML_TEMPLATES,
    DEFAULT_TEMPLATES,
    default_routing_rules,
)


test_engine = create_engine(test_url)


@pytest.fixture(autouse=True)
def clean_database():
    yield
    with Session(test_engine) as session:
        for model in (
            NotificationJob,
            PurchaseOrderAttachment,
            PurchaseOrderItem,
            PurchaseOrder,
            RedemptionItem,
            Redemption,
            RedemptionCode,
            Winner,
            EventPrizeAvailability,  # Must be before Prize (FK constraint)
            Prize,
            Event,
        ):
            session.execute(delete(model))
        session.execute(delete(NotificationRoutingRule))
        session.add_all(
            NotificationRoutingRule(event_type=event_type, channel=channel, recipient=recipient)
            for event_type, channel, recipient in default_routing_rules()
        )
        for event_type, text_template in DEFAULT_TEMPLATES.items():
            template = session.scalar(
                select(NotificationTemplate).where(NotificationTemplate.event_type == event_type)
            )
            if template is None:
                session.add(
                    NotificationTemplate(
                        event_type=event_type,
                        text_template=text_template,
                        html_template=DEFAULT_HTML_TEMPLATES[event_type],
                    )
                )
            else:
                template.text_template = text_template
                template.html_template = DEFAULT_HTML_TEMPLATES[event_type]
        session.commit()
