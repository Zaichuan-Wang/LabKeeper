#!/usr/bin/env bash
# 实验室库存管理系统 — 通用启动脚本（Linux / macOS）
# 用法：
#   ./start.sh                        # 默认端口启动
#   ./start.sh --api-port 9000        # 自定义后端端口
#   ./start.sh --frontend-port 8080   # 自定义前端端口
#   ./start.sh --nginx                # 使用 nginx 反向代理（跳过内置前端服务）
#   ./start.sh --nginx-port 5173      # nginx 对外端口提示（需与 nginx 配置一致）
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
fi

API_PORT=8000
FRONTEND_PORT=5173
NGINX=false
NGINX_PORT=5173
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
      echo "  --nginx-port PORT      nginx 对外端口提示（默认 5173，需与 nginx 配置一致）"
      echo "  --daemon               后台运行，优先脱离登录会话，日志写入 data/*.log"
      echo "  --stop                 停止所有后台进程（含 nginx）"
      exit 0 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

if [ "$STOP" = true ]; then
  stopped=0
  for f in "$PID_DIR"/*.unit; do
    [ -f "$f" ] || continue
    name=$(basename "$f" .unit)
    unit=$(cat "$f")
    manager_file="$PID_DIR/$name.manager"
    manager="pid"
    [ -f "$manager_file" ] && manager=$(cat "$manager_file")
    if [ "$manager" = "user" ] && command -v systemctl &>/dev/null; then
      systemctl --user stop "$unit" 2>/dev/null && echo "已停止 $name ($unit)" && stopped=$((stopped + 1)) || true
    elif [ "$manager" = "system" ] && command -v sudo &>/dev/null; then
      if [ -t 0 ]; then
        sudo systemctl stop "$unit" 2>/dev/null && echo "已停止 $name ($unit)" && stopped=$((stopped + 1)) || true
      else
        sudo -n systemctl stop "$unit" 2>/dev/null && echo "已停止 $name ($unit)" && stopped=$((stopped + 1)) || true
      fi
    fi
    rm -f "$f" "$manager_file"
  done
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
    if [ -t 0 ]; then
      sudo nginx -s stop 2>/dev/null && echo "已停止 nginx" || true
    else
      sudo -n nginx -s stop 2>/dev/null && echo "已停止 nginx" || true
    fi
    stopped=$((stopped + 1))
  fi
  [ "$stopped" -eq 0 ] && echo "没有运行中的服务"
  exit 0
fi

find_python() {
  if [ -n "${PYTHON:-}" ] && command -v "$PYTHON" &>/dev/null; then
    command -v "$PYTHON"; return
  fi
  for env in labkeeper codex; do
    local conda_py="$HOME/miniforge3/envs/$env/bin/python"
    [ -x "$conda_py" ] && echo "$conda_py" && return
    conda_py="$HOME/miniconda3/envs/$env/bin/python"
    [ -x "$conda_py" ] && echo "$conda_py" && return
    conda_py="$HOME/anaconda3/envs/$env/bin/python"
    [ -x "$conda_py" ] && echo "$conda_py" && return
  done
  if command -v python3 &>/dev/null; then
    command -v python3; return
  fi
  command -v python || echo "python"; return
}

PY=$(find_python)
echo "Python: $PY"
echo "运行模式: ${LABKEEPER_ENV:-production}"
mkdir -p "$DATA_DIR" "$PID_DIR"

add_systemd_env() {
  local key="$1"
  [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || return
  [ -n "${!key+x}" ] || return
  SYSTEMD_ENV_ARGS+=("--setenv=$key=${!key}")
}

build_systemd_env_args() {
  SYSTEMD_ENV_ARGS=()
  add_systemd_env HOME
  add_systemd_env PATH
  while IFS='=' read -r key _; do
    [[ "$key" == LABKEEPER_* ]] || continue
    add_systemd_env "$key"
  done < <(env)
}

daemon_unit_name() {
  local name="$1"
  local suffix
  if command -v cksum &>/dev/null; then
    suffix=$(printf "%s" "$ROOT" | cksum | awk '{print $1}')
  else
    suffix=$(basename "$ROOT")
  fi
  echo "labkeeper-$name-$suffix.service"
}

systemd_user_survives_logout() {
  local current_user
  current_user="${USER:-$(id -un)}"
  [ "$(loginctl show-user "$current_user" -p Linger --value 2>/dev/null || true)" = "yes" ]
}

run_sudo() {
  if [ -t 0 ]; then
    sudo "$@"
  else
    sudo -n "$@"
  fi
}

can_sudo() {
  if ! command -v sudo &>/dev/null; then
    return 1
  fi
  if [ -t 0 ]; then
    sudo -v
  else
    sudo -n true
  fi
}

start_systemd_daemon() {
  local manager="$1"
  local unit="$2"
  local name="$3"
  local stdout_log="$4"
  local stderr_log="$5"
  shift 5

  local bash_path
  bash_path="$(command -v bash || true)"
  [ -n "$bash_path" ] || return 1

  build_systemd_env_args
  if [ "$manager" = "user" ]; then
    systemd-run --user \
      --unit="$unit" \
      --description="LabKeeper $name" \
      --collect \
      --property=Restart=no \
      "${SYSTEMD_ENV_ARGS[@]}" \
      "$bash_path" -c 'stdout=$1; stderr=$2; workdir=$3; shift 3; cd "$workdir"; exec "$@" >"$stdout" 2>"$stderr"' \
      _ "$stdout_log" "$stderr_log" "$ROOT" "$@"
  else
    local current_user current_group
    current_user="$(id -un)"
    current_group="$(id -gn)"
    run_sudo systemd-run \
      --unit="$unit" \
      --description="LabKeeper $name" \
      --collect \
      --property=Restart=no \
      --property="User=$current_user" \
      --property="Group=$current_group" \
      "${SYSTEMD_ENV_ARGS[@]}" \
      "$bash_path" -c 'stdout=$1; stderr=$2; workdir=$3; shift 3; cd "$workdir"; exec "$@" >"$stdout" 2>"$stderr"' \
      _ "$stdout_log" "$stderr_log" "$ROOT" "$@"
  fi
}

systemd_main_pid() {
  local manager="$1"
  local unit="$2"
  if [ "$manager" = "user" ]; then
    systemctl --user show "$unit" -p MainPID --value 2>/dev/null || true
  else
    systemctl show "$unit" -p MainPID --value 2>/dev/null || true
  fi
}

systemd_is_active() {
  local manager="$1"
  local unit="$2"
  if [ "$manager" = "user" ]; then
    systemctl --user is-active --quiet "$unit"
  else
    systemctl is-active --quiet "$unit"
  fi
}

stop_systemd_daemon() {
  local manager="$1"
  local unit="$2"
  if [ "$manager" = "user" ]; then
    systemctl --user stop "$unit" 2>/dev/null || true
  else
    run_sudo systemctl stop "$unit" 2>/dev/null || true
  fi
}

record_systemd_daemon() {
  local manager="$1"
  local unit="$2"
  local name="$3"
  local stdout_log="$4"
  local stderr_log="$5"
  local pid_file="$6"
  local unit_file="$7"
  local manager_file="$8"
  local label="$9"

  local pid
  sleep 0.5
  if ! systemd_is_active "$manager" "$unit"; then
    echo "  $name 启动失败，请查看日志: $stdout_log / $stderr_log" >&2
    return 1
  fi
  pid=$(systemd_main_pid "$manager" "$unit")
  echo "$unit" > "$unit_file"
  echo "$manager" > "$manager_file"
  echo "${pid:-0}" > "$pid_file"
  echo "  $label: $unit  PID: ${pid:-未知}  日志: $DATA_DIR/$name.*.log"
}

start_daemon() {
  local name="$1"
  local stdout_log="$DATA_DIR/$name.out.log"
  local stderr_log="$DATA_DIR/$name.err.log"
  local pid_file="$PID_DIR/$name.pid"
  local unit_file="$PID_DIR/$name.unit"
  local manager_file="$PID_DIR/$name.manager"
  shift

  : > "$stdout_log"
  : > "$stderr_log"

  if [ -d /run/systemd/system ] && command -v systemd-run &>/dev/null && command -v systemctl &>/dev/null; then
    local unit
    unit=$(daemon_unit_name "$name")
    if command -v loginctl &>/dev/null && systemd_user_survives_logout && systemctl --user show-environment >/dev/null 2>&1; then
      if start_systemd_daemon user "$unit" "$name" "$stdout_log" "$stderr_log" "$@"; then
        if record_systemd_daemon user "$unit" "$name" "$stdout_log" "$stderr_log" "$pid_file" "$unit_file" "$manager_file" "systemd 用户服务"; then
          return
        fi
        stop_systemd_daemon user "$unit"
      fi
    fi
    if can_sudo; then
      if start_systemd_daemon system "$unit" "$name" "$stdout_log" "$stderr_log" "$@"; then
        if record_systemd_daemon system "$unit" "$name" "$stdout_log" "$stderr_log" "$pid_file" "$unit_file" "$manager_file" "systemd 服务"; then
          return
        fi
        stop_systemd_daemon system "$unit"
      fi
    fi
    echo "  systemd daemon 启动不可用，回退到 setsid/nohup；若服务器清理登录会话，请启用 linger 或用 systemd 部署。" >&2
  fi

  # nohup only ignores SIGHUP; setsid also detaches the service from the SSH
  # login session on non-systemd systems.
  if command -v setsid &>/dev/null; then
    nohup setsid "$@" </dev/null > "$stdout_log" 2> "$stderr_log" &
  else
    nohup "$@" </dev/null > "$stdout_log" 2> "$stderr_log" &
  fi

  local pid=$!
  echo "$pid" > "$pid_file"
  sleep 0.2
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "  $name 启动失败，请查看日志: $stdout_log / $stderr_log" >&2
    return 1
  fi
  echo "  PID: $pid  日志: $DATA_DIR/$name.*.log"
}

echo "启动后端: http://127.0.0.1:$API_PORT"
if [ "$DAEMON" = true ]; then
  start_daemon backend "$PY" "$BACKEND" --host 0.0.0.0 --port "$API_PORT"
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
    start_daemon frontend "$PY" -m http.server "$FRONTEND_PORT" -d "$FRONTEND_DIR"
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
