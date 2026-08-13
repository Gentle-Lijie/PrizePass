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
process_names=()
cleanup_started=false

cleanup() {
  if [[ "$cleanup_started" == true ]]; then
    return
  fi
  cleanup_started=true
  trap - INT TERM EXIT
  for pid in "${pids[@]}"; do
    kill -TERM -- "-$pid" 2>/dev/null || true
  done

  local deadline=$((SECONDS + 5))
  local groups_alive=true
  while [[ "$groups_alive" == true && $SECONDS -lt $deadline ]]; do
    groups_alive=false
    for pid in "${pids[@]}"; do
      if kill -0 -- "-$pid" 2>/dev/null; then
        groups_alive=true
        break
      fi
    done
    if [[ "$groups_alive" == true ]]; then
      sleep 0.1
    fi
  done

  for pid in "${pids[@]}"; do
    kill -KILL -- "-$pid" 2>/dev/null || true
  done
  for pid in "${pids[@]}"; do
    wait "$pid" 2>/dev/null || true
  done
}

handle_signal() {
  local exit_code="$1"
  cleanup
  exit "$exit_code"
}

trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM
trap cleanup EXIT

# Job control gives every background service its own process group. Killing the
# group also reaches uvicorn's reload child and npm/Vite descendants.
set -m
(cd "$ROOT_DIR/backend" && exec "$ROOT_DIR/.venv/bin/uvicorn" app.main:app --reload --host 127.0.0.1 --port "${APP_PORT:-8007}") &
pids+=("$!")
process_names+=("API")
(cd "$ROOT_DIR/backend" && exec "$ROOT_DIR/.venv/bin/python" -m app.worker) &
pids+=("$!")
process_names+=("worker")
npm --prefix "$ROOT_DIR/frontend" run dev &
pids+=("$!")
process_names+=("frontend")

while true; do
  for index in "${!pids[@]}"; do
    pid="${pids[$index]}"
    if ! kill -0 "$pid" 2>/dev/null; then
      if wait "$pid"; then
        status=0
      else
        status=$?
      fi
      echo "核心进程已退出：${process_names[$index]}（状态码 $status）。" >&2
      if ((status == 0)); then
        exit 1
      fi
      exit "$status"
    fi
  done
  sleep 1
done
