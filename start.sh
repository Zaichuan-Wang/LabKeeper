#!/usr/bin/env bash
# 实验室库存管理系统 — 通用启动脚本（Linux / macOS）
# 用法：
#   ./start.sh                        # 默认端口启动
#   ./start.sh --api-port 9000        # 自定义后端端口
#   ./start.sh --frontend-port 8080   # 自定义前端端口
#   ./start.sh --nginx                # 使用 nginx 反向代理（跳过内置前端服务）
#   ./start.sh --nginx-port 20829     # 指定 nginx 监听端口（默认 20829）
#   ./start.sh --daemon               # 后台运行，输出到 data/*.log
#   ./start.sh --stop                 # 停止所有后台进程（含 nginx）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend/server.py"
FRONTEND_DIR="$ROOT/frontend"
DATA_DIR="$ROOT/data"
PID_DIR="$DATA_DIR/pids"

if [ ! -f "$ROOT/.env" ] && [ -z "${LABKEEPER_ENV:-}" ]; then
  export LABKEEPER_ENV=development
  export LABKEEPER_ENABLE_DEV_TOOLS=1
fi

API_PORT=8000
FRONTEND_PORT=5173
NGINX=false
NGINX_PORT=20829
DAEMON=false
STOP=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-port) API_PORT="$2"; shift 2 ;;
    --frontend-port) FRONTEND_PORT="$2"; shift 2 ;;
    --nginx) NGINX=true; shift ;;
    --nginx-port) NGINX_PORT="$2"; shift 2 ;;
    --daemon) DAEMON=true; shift ;;
    --stop) STOP=true; shift ;;
    --help|-h)
      echo "用法: $0 [--api-port PORT] [--frontend-port PORT] [--nginx] [--nginx-port PORT] [--daemon] [--stop]"
      echo ""
      echo "  --api-port PORT        后端 API 端口（默认 8000）"
      echo "  --frontend-port PORT   前端页面端口（默认 5173，--nginx 时忽略）"
      echo "  --nginx                使用 nginx 反向代理，不启动内置前端服务"
      echo "  --nginx-port PORT      nginx 监听端口（默认 20829）"
      echo "  --daemon               后台运行，日志写入 data/*.log"
      echo "  --stop                 停止所有后台进程（含 nginx）"
      exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

if [ "$STOP" = true ]; then
  stopped=0
  for f in "$PID_DIR"/*.pid; do
    [ -f "$f" ] || continue
    pid=$(cat "$f")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && echo "已停止 $(basename "$f" .pid) (PID $pid)" || true
      stopped=$((stopped + 1))
    fi
    rm -f "$f"
  done
  # 停止 nginx
  if command -v nginx &>/dev/null && pgrep -x nginx &>/dev/null; then
    sudo nginx -s stop 2>/dev/null && echo "已停止 nginx" || true
    stopped=$((stopped + 1))
  fi
  [ "$stopped" -eq 0 ] && echo "没有运行中的服务"
  exit 0
fi

find_python() {
  if [ -n "${PYTHON:-}" ] && command -v "$PYTHON" &>/dev/null; then
    echo "$PYTHON"; return
  fi
  for env in labkeeper lab_position codex; do
    local conda_py="$HOME/miniforge3/envs/$env/bin/python"
    [ -x "$conda_py" ] && echo "$conda_py" && return
    conda_py="$HOME/miniconda3/envs/$env/bin/python"
    [ -x "$conda_py" ] && echo "$conda_py" && return
    conda_py="$HOME/anaconda3/envs/$env/bin/python"
    [ -x "$conda_py" ] && echo "$conda_py" && return
  done
  if command -v python3 &>/dev/null; then
    echo "python3"; return
  fi
  echo "python"; return
}

PY=$(find_python)
echo "Python: $PY"
echo "运行模式: ${LABKEEPER_ENV:-production}"
mkdir -p "$DATA_DIR" "$PID_DIR"

echo "启动后端: http://127.0.0.1:$API_PORT"
if [ "$DAEMON" = true ]; then
  nohup "$PY" "$BACKEND" --host 0.0.0.0 --port "$API_PORT" \
    > "$DATA_DIR/backend.out.log" 2> "$DATA_DIR/backend.err.log" &
  echo $! > "$PID_DIR/backend.pid"
  echo "  PID: $(cat "$PID_DIR/backend.pid")  日志: $DATA_DIR/backend.*.log"
else
  "$PY" "$BACKEND" --host 127.0.0.1 --port "$API_PORT" &
  echo $! > "$PID_DIR/backend.pid"
fi

if [ "$NGINX" = true ]; then
  echo "启动 nginx 反向代理: http://0.0.0.0:$NGINX_PORT"
  # 先停止已有的 nginx 进程
  if pgrep -x nginx &>/dev/null; then
    sudo nginx -s stop 2>/dev/null || true
    sleep 0.5
  fi
  sudo nginx
  echo "  nginx 已启动，前端页面通过 http://服务器IP:$NGINX_PORT 访问"
else
  echo "启动前端: http://127.0.0.1:$FRONTEND_PORT"
  if [ "$DAEMON" = true ]; then
    nohup "$PY" -m http.server "$FRONTEND_PORT" -d "$FRONTEND_DIR" \
      > "$DATA_DIR/frontend.out.log" 2> "$DATA_DIR/frontend.err.log" &
    echo $! > "$PID_DIR/frontend.pid"
    echo "  PID: $(cat "$PID_DIR/frontend.pid")  日志: $DATA_DIR/frontend.*.log"
  else
    "$PY" -m http.server "$FRONTEND_PORT" -d "$FRONTEND_DIR" &
    echo $! > "$PID_DIR/frontend.pid"
  fi
fi

echo ""
if [ "$NGINX" = true ]; then
  echo "打开浏览器: http://127.0.0.1:$NGINX_PORT"
else
  echo "打开浏览器: http://127.0.0.1:$FRONTEND_PORT"
fi
if [ "$DAEMON" = false ]; then
  echo "按 Ctrl+C 停止所有服务"
  wait
fi
