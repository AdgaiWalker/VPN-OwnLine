#!/usr/bin/env bash
# 查看 Ladder 统一运行日志与服务日志
#
# 用法：
#   ./server/log.sh                     # 查看最近 30 条事件日志
#   ./server/log.sh -n 100              # 查看最近 100 条
#   ./server/log.sh -f                  # 实时追踪事件日志 (tail -f)
#   ./server/log.sh --err               # 仅看异常告警 (WARN / ERROR)
#   ./server/log.sh --sub               # 仅看订阅拉取记录
#   ./server/log.sh --sing-box          # 查看底层 sing-box 运行日志
#   ./server/log.sh --caddy             # 查看 Caddy 反代日志
#   ./server/log.sh --admin             # 查看 admin 管理服务日志
set -euo pipefail

DATA="${LADDER_DATA:-/opt/web-data}"
LOG_FILE="$DATA/events.log"
NUM=30
FOLLOW=0
FILTER=""
SERVICE=""

while [ $# -gt 0 ]; do
  case "$1" in
    -n)
      NUM="$2"; shift 2 ;;
    -f)
      FOLLOW=1; shift ;;
    --err)
      FILTER="WARN|ERROR"; shift ;;
    --sub)
      FILTER="SUB"; shift ;;
    --sing-box)
      SERVICE="sing-box"; shift ;;
    --caddy)
      SERVICE="caddy"; shift ;;
    --admin)
      SERVICE="admin"; shift ;;
    --service)
      SERVICE="$2"; shift 2 ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then NUM="$1"; else echo "未知选项: $1"; exit 1; fi
      shift ;;
  esac
done

# 如果指定了底层服务，直接打印该服务的 systemd / 文件日志
if [ -n "$SERVICE" ]; then
  echo -e "\033[1;36m==> 服务日志: $SERVICE (最近 $NUM 行)\033[0m"
  if [ "$SERVICE" = "sing-box" ] && [ -f /var/log/sing-box.log ]; then
    if [ "$FOLLOW" = 1 ]; then
      tail -f -n "$NUM" /var/log/sing-box.log
    else
      tail -n "$NUM" /var/log/sing-box.log
    fi
  else
    if [ "$FOLLOW" = 1 ]; then
      journalctl -u "$SERVICE.service" -f -n "$NUM" --no-pager
    else
      journalctl -u "$SERVICE.service" -n "$NUM" --no-pager
    fi
  fi
  exit 0
fi

if [ ! -f "$LOG_FILE" ]; then
  echo "暂无运行日志文件 ($LOG_FILE)"
  exit 0
fi

# 彩色格式化函数
format_log() {
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    ts=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('ts',''))" "$line" 2>/dev/null || echo "")
    lvl=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('level',''))" "$line" 2>/dev/null || echo "")
    src=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('src',''))" "$line" 2>/dev/null || echo "")
    msg=$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('msg',''))" "$line" 2>/dev/null || echo "$line")

    case "$lvl" in
      ERROR)   color="\033[31m" ;; # 红
      WARN)    color="\033[33m" ;; # 黄
      SUCCESS) color="\033[32m" ;; # 绿
      INFO)    color="\033[36m" ;; # 青
      *)       color="\033[0m"  ;;
    esac
    reset="\033[0m"

    printf "%s ${color}[%-7s]${reset} \033[1m[%-5s]\033[0m %s\n" "$ts" "$lvl" "$src" "$msg"
  done
}

echo -e "\033[1;36m==> Ladder 运行事件日志 (最近 $NUM 行)\033[0m"
if [ "$FOLLOW" = 1 ]; then
  if [ -n "$FILTER" ]; then
    tail -f -n "$NUM" "$LOG_FILE" | grep --line-buffered -E "$FILTER" | format_log
  else
    tail -f -n "$NUM" "$LOG_FILE" | format_log
  fi
else
  if [ -n "$FILTER" ]; then
    tail -n "$NUM" "$LOG_FILE" | grep -E "$FILTER" | format_log
  else
    tail -n "$NUM" "$LOG_FILE" | format_log
  fi
fi
