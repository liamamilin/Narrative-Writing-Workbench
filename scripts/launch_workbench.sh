#!/bin/bash
# Narrative Writing Workbench — launch helper (idempotent).
# Usage: scripts/launch_workbench.sh [stop]
# Idle auto-exit: after WORKBENCH_IDLE_TIMEOUT minutes without any request
# the server shuts itself down (default 30; 0 disables). Restart with this
# script anytime (idempotent).
# Credentials live in workbench/settings.json (git-ignored). No env file needed:
# workbench/server.py applies them into the process env at startup.
#
# Resolve the repo root from this script's own path. Do NOT rely on
# BASH_SOURCE[0] alone: when the .app launcher runs us through `zsh -l`,
# BASH_SOURCE is empty and dirname("") silently resolves to the parent
# directory (server would start in the wrong cwd).
SCRIPT="$0"
[ -z "$SCRIPT" ] && SCRIPT="${BASH_SOURCE[0]}"
case "$SCRIPT" in
  /*) ;;
  *) SCRIPT="$(pwd)/$SCRIPT" ;;
esac
DIR="$(cd "$(dirname "$SCRIPT")/.." && pwd)"
cd "$DIR" || { echo "找不到项目目录: $DIR"; exit 1; }
[ -d workbench ] || { echo "目录不正确(缺少 workbench/): $DIR"; exit 1; }

PORT="${WORKBENCH_PORT:-8600}"
URL="http://127.0.0.1:${PORT}"

if [ "$1" = "stop" ]; then
  lsof -ti:"$PORT" | xargs kill 2>/dev/null && echo "已停止 $URL" || echo "没有在运行的实例"
  exit 0
fi

if curl -s -m 2 "$URL/settings" >/dev/null 2>&1; then
  echo "已在运行: $URL"; open "$URL" 2>/dev/null || true; exit 0
fi

PY=""
for p in "$HOME/.pyenv/shims/python3" "$HOME/.pyenv/bin/python3" \
         /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         "$(command -v python3)" /usr/bin/python3 python; do
  [ -n "$p" ] && [ -x "$p" ] && "$p" -c "import fastapi,uvicorn" 2>/dev/null && { PY="$p"; break; }
done
[ -z "$PY" ] && { echo "未找到带 fastapi/uvicorn 的 python3,先运行: pip install -r requirements.txt -r requirements-workbench.txt"; exit 1; }

mkdir -p .scratch
WORKBENCH_PORT="$PORT" nohup "$PY" -m workbench.server > .scratch/workbench.log 2>&1 &
for i in $(seq 1 20); do curl -s -m 1 "$URL/settings" >/dev/null 2>&1 && break; sleep 1; done
if ! curl -s -m 2 "$URL/settings" >/dev/null 2>&1; then
  echo "启动失败,服务日志(.scratch/workbench.log)末尾:"
  tail -5 .scratch/workbench.log
  exit 1
fi
echo "启动完成: $URL (engine=$(curl -s "$URL/settings" | sed 's/.*"engine":"\([^"]*\)".*/\1/'))"
open "$URL" 2>/dev/null || true
