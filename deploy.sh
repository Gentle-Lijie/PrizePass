#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
[[ -f "$ENV_FILE" ]] || { echo "缺少 .env" >&2; exit 1; }
set -a
source "$ENV_FILE"
set +a

for command_name in python3.12 node npm pm2 mysqladmin curl; do
  command -v "$command_name" >/dev/null || { echo "缺少依赖：$command_name" >&2; exit 1; }
done
[[ -n "${DATABASE_URL:-}" && -n "${UPLOAD_DIR:-}" ]] || { echo "DATABASE_URL 和 UPLOAD_DIR 必须配置" >&2; exit 1; }

[[ -x "$ROOT_DIR/.venv/bin/python" ]] || python3.12 -m venv "$ROOT_DIR/.venv"
"$ROOT_DIR/.venv/bin/pip" install --requirement "$ROOT_DIR/backend/requirements.txt"
mkdir -p "$UPLOAD_DIR/prizes" "$ROOT_DIR/logs"
test -w "$UPLOAD_DIR/prizes" || { echo "上传目录不可写" >&2; exit 1; }
(cd "$ROOT_DIR/backend" && "$ROOT_DIR/.venv/bin/python" - <<'PY'
from sqlalchemy import create_engine, text
from app.config import get_settings
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
with engine.connect() as connection:
    connection.execute(text("SELECT 1"))
print("MySQL 连接检查通过")
PY
)
npm --prefix "$ROOT_DIR/frontend" ci
npm --prefix "$ROOT_DIR/frontend" run build

(cd "$ROOT_DIR/backend" && "$ROOT_DIR/.venv/bin/alembic" upgrade head)

(cd "$ROOT_DIR" && pm2 startOrReload ecosystem.config.cjs --env production --update-env)
pm2 save
sleep 2
curl --fail --silent --show-error "http://127.0.0.1:${APP_PORT:-8007}/api/health" >/dev/null
pm2 describe prizepass-api | grep -q 'online'
pm2 describe prizepass-worker | grep -q 'online'
