#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "缺少 .env，请复制 .env.example 后填写配置。" >&2
  exit 1
fi
set -a
source "$ENV_FILE"
set +a

for command_name in python3.12 node npm mysql; do
  command -v "$command_name" >/dev/null || { echo "缺少依赖：$command_name" >&2; exit 1; }
done

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  python3.12 -m venv "$ROOT_DIR/.venv"
fi
"$ROOT_DIR/.venv/bin/pip" install -r "$ROOT_DIR/backend/requirements.txt"
if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  npm --prefix "$ROOT_DIR/frontend" install
fi
mkdir -p "$UPLOAD_DIR/prizes"

(cd "$ROOT_DIR/backend" && "$ROOT_DIR/.venv/bin/python" - <<'PY'
import re

import pymysql
from sqlalchemy.engine import make_url

from app.config import get_settings

url = make_url(get_settings().database_url)
if url.get_backend_name() != "mysql" or not url.database:
    raise SystemExit("DATABASE_URL 必须指向 MySQL 数据库")
if not re.fullmatch(r"[A-Za-z0-9_]+", url.database):
    raise SystemExit("数据库名只能包含字母、数字和下划线")
connection = pymysql.connect(
    host=url.host or "127.0.0.1",
    port=url.port or 3306,
    user=url.username or "",
    password=url.password or "",
    charset="utf8mb4",
    autocommit=True,
)
try:
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE DATABASE IF NOT EXISTS `{url.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
finally:
    connection.close()
print(f"MySQL 数据库 {url.database} 已就绪")
PY
)

(cd "$ROOT_DIR/backend" && "$ROOT_DIR/.venv/bin/alembic" upgrade head)
TEST_DATABASE_URL="$(cd "$ROOT_DIR/backend" && "$ROOT_DIR/.venv/bin/python" - <<'PY'
from sqlalchemy.engine import make_url
from app.config import get_settings
url = make_url(get_settings().database_url)
print(url.set(database=f"{url.database}_test").render_as_string(hide_password=False))
PY
)"
(cd "$ROOT_DIR/backend" && DATABASE_URL="$TEST_DATABASE_URL" "$ROOT_DIR/.venv/bin/python" - <<'PY'
import pymysql
from sqlalchemy.engine import make_url
from app.config import get_settings
url = make_url(get_settings().database_url)
connection = pymysql.connect(host=url.host or "127.0.0.1", port=url.port or 3306, user=url.username or "", password=url.password or "", charset="utf8mb4", autocommit=True)
try:
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{url.database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
finally:
    connection.close()
PY
)
(cd "$ROOT_DIR/backend" && DATABASE_URL="$TEST_DATABASE_URL" "$ROOT_DIR/.venv/bin/alembic" upgrade head)
export TEST_DATABASE_URL

if [[ "${1:-}" == "seed" ]]; then
  (cd "$ROOT_DIR/backend" && "$ROOT_DIR/.venv/bin/python" -m app.seed)
  exit 0
fi
if [[ $# -gt 0 ]]; then
  echo "用法：./dev.sh [seed]" >&2
  exit 2
fi

pids=()
cleanup() {
  trap - INT TERM EXIT
  if ((${#pids[@]})); then
    kill "${pids[@]}" 2>/dev/null || true
    wait "${pids[@]}" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

(cd "$ROOT_DIR/backend" && exec "$ROOT_DIR/.venv/bin/uvicorn" app.main:app --reload --host 127.0.0.1 --port "${APP_PORT:-8007}") & pids+=("$!")
(cd "$ROOT_DIR/backend" && exec "$ROOT_DIR/.venv/bin/python" -m app.worker) & pids+=("$!")
npm --prefix "$ROOT_DIR/frontend" run dev & pids+=("$!")

while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" || status=$?
      echo "核心进程已退出。" >&2
      exit "${status:-1}"
    fi
  done
  sleep 1
done
