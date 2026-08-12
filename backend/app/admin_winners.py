import secrets
from typing import Annotated, Any

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .admin_events import get_event_or_404
from .auth import require_admin_password
from .database import get_db
from .http import fail
from .models import (
    CodeStatus,
    NotificationChannel,
    NotificationJob,
    NotificationStatus,
    RedemptionCode,
    Winner,
)
from .notifications import (
    code_issued_context,
    create_notification_pair,
    render_template,
    template_text,
)
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
WINNER_EXPORT_HEADERS = [
    "external_id",
    "name",
    "email",
    "quota",
    "code",
    "code_status",
    "email_notification_status",
    "webhook_notification_status",
    "created_at",
]
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


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
    if table.headers not in (WINNER_HEADERS, WINNER_HEADERS_EXTERNAL):
        return {
            "valid": False,
            "rows": [],
            "errors": [{"row": 1, "field": "header", "message": "表头必须为 name,email,quota 或 external_id,name,email,quota"}],
            "count": 0,
            "quota_total": 0,
        }
    has_external = table.headers == WINNER_HEADERS_EXTERNAL
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
        normalized: dict[str, Any] = {"external_id": external_id, "name": name}
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
    content, media_type = template_bytes(WINNER_HEADERS_EXTERNAL, format)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="winners-template.{format}"'})


@router.post("/events/{event_id}/winners/import/validate")
async def validate_winners(event_id: int, db: DbSession, file: Annotated[UploadFile, File()]) -> dict:
    get_event_or_404(db, event_id)
    return validate_winner_table(db, event_id, file.filename or "", await file.read(MAX_FILE_SIZE + 1))


@router.post("/events/{event_id}/winners/import/confirm", status_code=201)
async def confirm_winners(event_id: int, db: DbSession, file: Annotated[UploadFile, File()]) -> dict:
    event = get_event_or_404(db, event_id)
    content = await file.read(MAX_FILE_SIZE + 1)
    result = validate_winner_table(db, event_id, file.filename or "", content)
    if not result["valid"]:
        fail(422, "invalid_import", "表格存在错误，未导入任何获奖人", {"errors": result["errors"]})
    codes = generate_codes(db, len(result["rows"]))
    template = template_text(db, "code_issued")
    for row, code_value in zip(result["rows"], codes, strict=True):
        identity_key = f"external:{row['external_id']}" if row["external_id"] else f"email:{row['email']}"
        winner = Winner(event_id=event_id, identity_key=identity_key, **row)
        db.add(winner)
        db.flush()
        code = RedemptionCode(
            event_id=event_id,
            winner_id=winner.id,
            code=code_value,
            quota=winner.quota,
            status=CodeStatus.ISSUED,
        )
        db.add(code)
        text_rendered = render_template(template, code_issued_context(winner, code_value, event))
        create_notification_pair(
            db,
            event_type="code_issued",
            text_rendered=text_rendered,
            email_destination=winner.email,
            winner_id=winner.id,
        )
    db.commit()
    return {"imported": len(result["rows"])}


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
            "quota": winner.quota,
            "code": code.code,
            "code_status": code.status.value,
            "email_notification_status": statuses.get((winner.id, NotificationChannel.EMAIL.value), NotificationStatus.PENDING).value,
            "webhook_notification_status": statuses.get((winner.id, NotificationChannel.WEBHOOK.value), NotificationStatus.PENDING).value,
            "created_at": utc_iso(winner.created_at),
        }
        for winner, code in rows
    ]


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
