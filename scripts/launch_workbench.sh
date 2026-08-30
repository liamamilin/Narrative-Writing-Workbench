#!/bin/bash
# Narrative Writing Workbench — launch helper (idempotent).
# Usage: scripts/launch_workbench.sh [stop]
# Credentials live in workbench/settings.json (git-ignored). No env file needed:
# workbench/server.py applies them into the process env at startup.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${WORKBENCH_PORT:-8600}"
URL="http://127.0.0.1:${PORT}"

if [ "$1" = "stop" ]; then
  lsof -ti:"$PORT" | xargs kill 2>/dev/null && echo "已停止 $URL" || echo "没有在运行的实例"
  exit 0
fi

if curl -s -m 2 "$URL/settings" >/dev/null 2>&1; then
  echo "已在运行: $URL"; open "$URL" 2>/dev/null || true; exit 0
fi

cd "$DIR" || { echo "找不到项目目录"; exit 1; }

PY=""
for p in "$(command -v python3)" /usr/bin/python3 python; do
  [ -x "$p" ] && "$p" -c "import fastapi,uvicorn" 2>/dev/null && { PY="$p"; break; }
done
[ -z "$PY" ] && { echo "未找到带 fastapi/uvicorn 的 python3,先运行: pip install -r requirements.txt -r requirements-workbench.txt"; exit 1; }

mkdir -p .scratch
WORKBENCH_PORT="$PORT" nohup "$PY" -m workbench.server > .scratch/workbench.log 2>&1 &
for i in $(seq 1 15); do curl -s -m 1 "$URL/settings" >/dev/null 2>&1 && break; sleep 1; done
echo "启动完成: $URL (engine=$(curl -s "$URL/settings" | sed 's/.*"engine":"\([^"]*\)".*/\1/'))"
open "$URL" 2>/dev/null || true
