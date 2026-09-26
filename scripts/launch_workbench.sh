#!/bin/bash
# Narrative Writing Workbench — launch helper (idempotent).
# Usage: scripts/launch_workbench.sh [stop]
# Idle auto-exit: after WORKBENCH_IDLE_TIMEOUT minutes without any request
# the worker shuts itself down (default 30; 0 disables). The launcher proxy
# keeps the URL listening and wakes a worker on the next browser request.
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
LOCAL_URL="http://127.0.0.1:${PORT}"

detect_lan_ip() {
  for iface in en0 en1; do
    ipconfig getifaddr "$iface" 2>/dev/null && return 0
  done
  return 1
}

# Binding to all interfaces makes the same running service reachable from a
# phone on the Wi-Fi. Set WORKBENCH_HOST=127.0.0.1 for local-only mode.
BIND_HOST="${WORKBENCH_HOST:-0.0.0.0}"
LAN_ENABLED=1
case "$BIND_HOST" in
  127.0.0.1|localhost|::1) LAN_ENABLED=0 ;;
esac
LAN_IP="127.0.0.1"
if [ "$LAN_ENABLED" -eq 1 ]; then
  LAN_IP="${WORKBENCH_ADVERTISED_HOST:-$(detect_lan_ip || true)}"
  [ -z "$LAN_IP" ] && LAN_IP="127.0.0.1"
fi
URL="$LOCAL_URL"
LAN_URL="http://${LAN_IP}:${PORT}"

if [ "$1" = "stop" ]; then
  lsof -ti:"$PORT" | xargs kill 2>/dev/null && echo "已停止 $URL" || echo "没有在运行的实例"
  exit 0
fi

notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"纸墨写作台\"" \
    >/dev/null 2>&1 || true
}
open_browser() {
  open "$URL" 2>/dev/null || \
  /usr/bin/osascript -e "open location \"$URL\"" >/dev/null 2>&1 || true
}

if curl -s -m 2 "$URL/settings" >/dev/null 2>&1; then
  echo "已在运行: $URL"
  [ "$LAN_ENABLED" -eq 1 ] && echo "手机访问: $LAN_URL"
  open_browser
  notify "服务已在运行,浏览器已打开本机地址"
  exit 0
fi

PY=""
for p in "$HOME/.pyenv/shims/python3" "$HOME/.pyenv/bin/python3" \
         /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         "$(command -v python3)" /usr/bin/python3 python; do
  [ -n "$p" ] && [ -x "$p" ] && "$p" -c "import fastapi,uvicorn" 2>/dev/null && { PY="$p"; break; }
done
[ -z "$PY" ] && { echo "未找到带 fastapi/uvicorn 的 python3,先运行: pip install -r requirements.txt -r requirements-workbench.txt"; exit 1; }

mkdir -p .scratch
WORKBENCH_PORT="$PORT" WORKBENCH_HOST="$BIND_HOST" nohup "$PY" -m workbench.wake > .scratch/workbench.log 2>&1 &
for i in $(seq 1 20); do curl -s -m 1 "$URL/settings" >/dev/null 2>&1 && break; sleep 1; done
if ! curl -s -m 2 "$URL/settings" >/dev/null 2>&1; then
  echo "启动失败,服务日志(.scratch/workbench.log)末尾:"
  tail -5 .scratch/workbench.log
  exit 1
fi
echo "启动完成: $URL (engine=$(curl -s "$URL/settings" | sed 's/.*"engine":"\([^"]*\)".*/\1/'))"
if [ "$LAN_ENABLED" -eq 0 ]; then
  echo "局域网访问已关闭（WORKBENCH_HOST=$BIND_HOST）"
elif [ "$LAN_IP" != "127.0.0.1" ]; then
  echo "手机访问(同一无线网络): $LAN_URL"
else
  echo "未检测到 Wi-Fi 地址；手机访问请设置 WORKBENCH_ADVERTISED_HOST=你的局域网IP 后重启。"
fi
open_browser
notify "服务已启动；手机访问地址已输出到终端"
