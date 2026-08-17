import secrets
from typing import Annotated, Any

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_events import get_event_or_404, maybe_open_event
from .auth import require_admin_password
from .config import get_settings
from .database import get_db
from .http import fail
from .models import (
    CodeStatus,
    Event,
    NotificationChannel,
    NotificationJob,
    NotificationStatus,
    RedemptionCode,
    Winner,
)
from .notifications import (
    code_issued_context,
    create_notification_jobs,
    render_html_template,
    render_template,
    template_content,
)
from .schemas import StrictModel
from .spreadsheets import (
    MAX_FILE_SIZE,
    export_csv,
    export_xlsx,
    parse_positive_integer,
    read_table,
    template_bytes,
)
from .timeutils import utc_iso


router = APIRouter(
    prefix="/admin",
    dependencies=[Depends(require_admin_password)],
    tags=["admin-winners"],
)
DbSession = Annotated[Session, Depends(get_db)]
WINNER_HEADERS = ["name", "email", "quota"]
WINNER_HEADERS_EXTERNAL = ["external_id", "name", "email", "quota"]
WINNER_HEADERS_AWARD = ["name", "email", "quota", "award_name"]
WINNER_HEADERS_EXTERNAL_AWARD = ["external_id", "name", "email", "quota", "award_name"]
WINNER_IMPORT_HEADERS = (
    WINNER_HEADERS,
    WINNER_HEADERS_EXTERNAL,
    WINNER_HEADERS_AWARD,
    WINNER_HEADERS_EXTERNAL_AWARD,
)
WINNER_EXPORT_HEADERS = [
    "external_id",
    "name",
    "email",
    "award_name",
    "quota",
    "code",
    "code_status",
    "email_notification_status",
    "webhook_notification_status",
    "created_at",
]
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class ResendNotificationRequest(StrictModel):
    channels: Annotated[list[NotificationChannel], Field(min_length=1, max_length=3)]


class QuotaUpdateRequest(StrictModel):
    quota: Annotated[int, Field(gt=0, le=4_294_967_295)]


class AwardUpdateRequest(StrictModel):
    award_name: Annotated[str | None, Field(default=None, max_length=200)] = None

    @field_validator("award_name")
    @classmethod
    def normalize_award_name(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class WinnerCreate(StrictModel):
    external_id: Annotated[str | None, Field(default=None, max_length=200)] = None
    name: Annotated[str, Field(min_length=1, max_length=100)]
    email: Annotated[str, Field(min_length=3, max_length=320)]
    quota: Annotated[int, Field(gt=0, le=4_294_967_295)]
    award_name: Annotated[str | None, Field(default=None, max_length=200)] = None

    @field_validator("award_name")
    @classmethod
    def normalize_award_name(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


def normalize_email(value: Any) -> str:
    raw = str(value).strip().lower() if value is not None else ""
    try:
        return validate_email(raw, check_deliverability=False).normalized.lower()
    except EmailNotValidError as exc:
        raise ValueError("邮箱格式不合法") from exc


def validate_winner_table(db: Session, event_id: int, filename: str, content: bytes) -> dict:
    try:
        table = read_table(filename, content)
    except ValueError as exc:
        return {"valid": False, "rows": [], "errors": [{"row": 0, "field": "file", "message": str(exc)}], "count": 0, "quota_total": 0}
    if table.headers not in WINNER_IMPORT_HEADERS:
        return {
            "valid": False,
            "rows": [],
            "errors": [{"row": 1, "field": "header", "message": "表头必须为 name,email,quota[,award_name] 或 external_id,name,email,quota[,award_name]"}],
            "count": 0,
            "quota_total": 0,
        }
    has_external = table.headers in (WINNER_HEADERS_EXTERNAL, WINNER_HEADERS_EXTERNAL_AWARD)
    rows: list[dict] = []
    errors: list[dict] = []
    emails_seen: dict[str, int] = {}
    external_seen: dict[str, int] = {}
    for row_no, raw in enumerate(table.rows, start=2):
        if len(raw) > len(table.headers):
            errors.append({"row": row_no, "field": "row", "message": "该行包含多余列"})
        values = list(raw) + [None] * (len(table.headers) - len(raw))
        source = dict(zip(table.headers, values[: len(table.headers)], strict=True))
        external_id = str(source.get("external_id") or "").strip() or None if has_external else None
        name = str(source.get("name") or "").strip()
        award_name = str(source.get("award_name") or "").strip() or None
        if award_name and len(award_name) > 200:
            errors.append({"row": row_no, "field": "award_name", "message": "奖项名称不能超过 200 字符"})
            award_name = None
        normalized: dict[str, Any] = {"external_id": external_id, "name": name, "award_name": award_name}
        if not name:
            errors.append({"row": row_no, "field": "name", "message": "姓名不能为空"})
        elif len(name) > 100:
            errors.append({"row": row_no, "field": "name", "message": "姓名不能超过 100 字符"})
        if external_id and len(external_id) > 200:
            errors.append({"row": row_no, "field": "external_id", "message": "external_id 不能超过 200 字符"})
        try:
            email = normalize_email(source.get("email"))
            normalized["email"] = email
            if email in emails_seen:
                errors.append({"row": row_no, "field": "email", "message": f"与第 {emails_seen[email]} 行邮箱重复"})
            else:
                emails_seen[email] = row_no
        except ValueError as exc:
            errors.append({"row": row_no, "field": "email", "message": str(exc)})
        if external_id:
            if external_id in external_seen:
                errors.append({"row": row_no, "field": "external_id", "message": f"与第 {external_seen[external_id]} 行 external_id 重复"})
            else:
                external_seen[external_id] = row_no
        try:
            normalized["quota"] = parse_positive_integer(source.get("quota"), "quota")
        except ValueError as exc:
            errors.append({"row": row_no, "field": "quota", "message": str(exc)})
        if "email" in normalized:
            normalized["identity_key"] = f"external:{external_id}" if external_id else f"email:{normalized['email']}"
        rows.append(normalized)

    identity_keys = [row["identity_key"] for row in rows if "identity_key" in row]
    existing = set(
        db.scalars(
            select(Winner.identity_key).where(
                Winner.event_id == event_id, Winner.identity_key.in_(identity_keys)
            )
        ).all()
    ) if identity_keys else set()
    for row_no, row in enumerate(rows, start=2):
        if row.get("identity_key") in existing:
            errors.append({"row": row_no, "field": "identity_key", "message": "该获奖人在当前比赛中已存在"})
    preview = [
        {key: value for key, value in row.items() if key != "identity_key"}
        for row in rows
    ]
    quota_total = sum(row.get("quota", 0) for row in rows)
    return {"valid": not errors, "rows": preview, "errors": errors, "count": len(rows), "quota_total": quota_total}


def generate_codes(db: Session, count: int) -> list[str]:
    codes: set[str] = set()
    while len(codes) < count:
        codes.add("".join(secrets.choice(CODE_ALPHABET) for _ in range(12)))
    existing = set(
        db.scalars(select(RedemptionCode.code).where(RedemptionCode.code.in_(codes))).all()
    )
    while existing:
        codes.difference_update(existing)
        while len(codes) < count:
            codes.add("".join(secrets.choice(CODE_ALPHABET) for _ in range(12)))
        existing = set(
            db.scalars(select(RedemptionCode.code).where(RedemptionCode.code.in_(codes))).all()
        )
    return list(codes)


@router.get("/events/{event_id}/winners/import/template")
def winner_template(event_id: int, db: DbSession, format: str = Query(pattern="^(csv|xlsx)$")) -> Response:
    get_event_or_404(db, event_id)
    content, media_type = template_bytes(WINNER_HEADERS_EXTERNAL_AWARD, format)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="winners-template.{format}"'})


@router.post("/events/{event_id}/winners/import/validate")
async def validate_winners(event_id: int, db: DbSession, file: Annotated[UploadFile, File()]) -> dict:
    get_event_or_404(db, event_id)
    return validate_winner_table(db, event_id, file.filename or "", await file.read(MAX_FILE_SIZE + 1))


def issue_winner(
    db: Session,
    event: Event,
    *,
    name: str,
    email: str,
    quota: int,
    external_id: str | None,
    award_name: str | None = None,
) -> Winner:
    """创建获奖人、签发兑换码并排发 code_issued 通知。调用方负责 commit。"""
    identity_key = f"external:{external_id}" if external_id else f"email:{email}"
    if db.scalar(
        select(Winner.id).where(
            Winner.event_id == event.id, Winner.identity_key == identity_key
        )
    ):
        fail(409, "winner_exists", "该获奖人在当前比赛中已存在")
    code_value = generate_codes(db, 1)[0]
    text_template, html_template = template_content(db, "code_issued")
    winner = Winner(
        event_id=event.id,
        identity_key=identity_key,
        external_id=external_id,
        name=name,
        email=email,
        award_name=award_name,
        quota=quota,
    )
    db.add(winner)
    db.flush()
    code = RedemptionCode(
        event_id=event.id,
        winner_id=winner.id,
        code=code_value,
        quota=winner.quota,
        status=CodeStatus.ISSUED,
    )
    db.add(code)
    context = code_issued_context(winner, code_value, event)
    text_rendered = render_template(text_template, context)
    html_rendered = render_html_template(html_template, context)
    create_notification_jobs(
        db,
        event_type="code_issued",
        text_rendered=text_rendered,
        winner_email=winner.email,
        html_rendered=html_rendered,
        winner_id=winner.id,
    )
    return winner


@router.post("/events/{event_id}/winners/import/confirm", status_code=201)
async def confirm_winners(event_id: int, db: DbSession, file: Annotated[UploadFile, File()]) -> dict:
    event = get_event_or_404(db, event_id)
    content = await file.read(MAX_FILE_SIZE + 1)
    result = validate_winner_table(db, event_id, file.filename or "", content)
    if not result["valid"]:
        fail(422, "invalid_import", "表格存在错误，未导入任何获奖人", {"errors": result["errors"]})
    for row in result["rows"]:
        issue_winner(
            db,
            event,
            name=row["name"],
            email=row["email"],
            quota=row["quota"],
            external_id=row["external_id"],
            award_name=row.get("award_name"),
        )
    maybe_open_event(event)
    db.commit()
    return {"imported": len(result["rows"])}


@router.post("/events/{event_id}/winners", status_code=201)
def add_winner(event_id: int, payload: WinnerCreate, db: DbSession) -> dict:
    event = get_event_or_404(db, event_id)
    try:
        email = normalize_email(payload.email)
    except ValueError:
        fail(422, "invalid_email", "邮箱格式不合法")
    external_id = (payload.external_id or "").strip() or None
    winner = issue_winner(
        db,
        event,
        name=payload.name.strip(),
        email=email,
        quota=payload.quota,
        external_id=external_id,
        award_name=payload.award_name,
    )
    maybe_open_event(event)
    db.commit()
    return {"imported": 1, "id": winner.id}


def winner_rows(db: Session, event_id: int) -> list[dict]:
    rows = db.execute(
        select(Winner, RedemptionCode)
        .join(RedemptionCode, RedemptionCode.winner_id == Winner.id)
        .where(Winner.event_id == event_id)
        .order_by(Winner.id)
    ).all()
    winner_ids = [winner.id for winner, _ in rows]
    jobs = db.scalars(
        select(NotificationJob)
        .where(NotificationJob.winner_id.in_(winner_ids), NotificationJob.event_type == "code_issued")
        .order_by(NotificationJob.created_at.desc(), NotificationJob.id.desc())
    ).all() if winner_ids else []
    statuses: dict[tuple[int, str], NotificationStatus] = {}
    for job in jobs:
        statuses.setdefault((job.winner_id, job.channel.value), job.status)
    return [
        {
            "id": winner.id,
            "external_id": winner.external_id,
            "name": winner.name,
            "email": winner.email,
            "award_name": winner.award_name,
            "quota": winner.quota,
            "code": code.code,
            "code_status": code.status.value,
            "email_notification_status": statuses.get((winner.id, NotificationChannel.EMAIL.value), NotificationStatus.PENDING).value,
            "webhook_notification_status": statuses.get((winner.id, NotificationChannel.WEBHOOK.value), NotificationStatus.PENDING).value,
            "created_at": utc_iso(winner.created_at),
        }
        for winner, code in rows
    ]


def winner_and_code_or_404(
    db: Session, winner_id: int, *, lock: bool = False
) -> tuple[Winner, RedemptionCode]:
    statement = (
        select(Winner, RedemptionCode)
        .join(RedemptionCode, RedemptionCode.winner_id == Winner.id)
        .where(Winner.id == winner_id)
    )
    if lock:
        statement = statement.with_for_update()
    row = db.execute(statement).one_or_none()
    if row is None:
        fail(404, "winner_not_found", "获奖人不存在")
    return row


@router.post("/winners/{winner_id}/notifications/resend", status_code=201)
def resend_winner_notification(
    winner_id: int, payload: ResendNotificationRequest, db: DbSession
) -> dict:
    winner, code = winner_and_code_or_404(db, winner_id)
    if code.status is not CodeStatus.ISSUED:
        fail(409, "code_not_notifiable", "只有未兑换且有效的兑换码可以重新通知")
    event = get_event_or_404(db, winner.event_id)
    channels = list(dict.fromkeys(payload.channels))
    if len(channels) != len(payload.channels):
        fail(422, "duplicate_notification_channel", "通知渠道不能重复选择")
    settings = get_settings()
    available = {
        NotificationChannel.EMAIL: bool(settings.smtp_host and settings.smtp_from_email),
        NotificationChannel.WEBHOOK: bool(settings.webhook_url),
        NotificationChannel.EMAIL_POSTER: bool(settings.email_poster_post_url),
    }
    unavailable = [channel.value for channel in channels if not available[channel]]
    if unavailable:
        fail(
            409,
            "notification_channel_unavailable",
            "所选通知渠道尚未配置",
            {"channels": unavailable},
        )
    text_template, html_template = template_content(db, "code_issued")
    context = code_issued_context(winner, code.code, event)
    text_rendered = render_template(text_template, context)
    html_rendered = render_html_template(html_template, context)
    jobs = [
        NotificationJob(
            event_type="code_issued",
            channel=channel,
            winner_id=winner.id,
            destination=settings.webhook_url
            if channel is NotificationChannel.WEBHOOK
            else winner.email,
            text_rendered=text_rendered,
            html_rendered=html_rendered,
            status=NotificationStatus.PENDING,
        )
        for channel in channels
    ]
    db.add_all(jobs)
    db.commit()
    return {"queued": len(jobs), "channels": [channel.value for channel in channels]}


@router.put("/winners/{winner_id}/quota")
def update_winner_quota(
    winner_id: int, payload: QuotaUpdateRequest, db: DbSession
) -> dict:
    winner, code = winner_and_code_or_404(db, winner_id, lock=True)
    if code.status is not CodeStatus.ISSUED:
        fail(409, "code_not_adjustable", "只有未兑换且有效的兑换码可以调整额度")
    winner.quota = payload.quota
    code.quota = payload.quota
    db.commit()
    return {"quota": payload.quota}


@router.put("/winners/{winner_id}/award")
def update_winner_award(
    winner_id: int, payload: AwardUpdateRequest, db: DbSession
) -> dict:
    winner, _ = winner_and_code_or_404(db, winner_id)
    winner.award_name = payload.award_name
    db.commit()
    return {"award_name": winner.award_name}


@router.post("/winners/{winner_id}/code/revoke")
def revoke_winner_code(winner_id: int, db: DbSession) -> dict:
    _, code = winner_and_code_or_404(db, winner_id, lock=True)
    if code.status is CodeStatus.REDEEMED:
        fail(409, "code_already_redeemed", "已兑换的兑换码不能撤销")
    if code.status is CodeStatus.DISABLED:
        fail(409, "code_already_revoked", "兑换码已撤销")
    code.status = CodeStatus.DISABLED
    db.commit()
    return {"code_status": code.status.value}


@router.get("/events/{event_id}/winners")
def list_winners(event_id: int, db: DbSession) -> list[dict]:
    get_event_or_404(db, event_id)
    return winner_rows(db, event_id)


@router.get("/events/{event_id}/winners/export")
def export_winners(event_id: int, db: DbSession, format: str = Query(pattern="^(csv|xlsx)$")) -> Response:
    get_event_or_404(db, event_id)
    rows = winner_rows(db, event_id)
    matrix = [[row[header] if row[header] is not None else "" for header in WINNER_EXPORT_HEADERS] for row in rows]
    if format == "csv":
        content, media_type = export_csv(WINNER_EXPORT_HEADERS, matrix), "text/csv; charset=utf-8"
    else:
        content, media_type = export_xlsx(WINNER_EXPORT_HEADERS, matrix), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="winners.{format}"'})
