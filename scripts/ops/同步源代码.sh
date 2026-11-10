#!/bin/bash
# 把本地工作区和 GitHub 对齐。
# 需要 GitHub 直连（Shadowrocket 隧道开着）或本脚本自动借道 walker-sv。
set -uo pipefail

[ -z "${HOME:-}" ] && { HOME="/Users/$(id -un)"; export HOME; }

TARGET="$(cd "$(dirname "$0")/../.." && pwd)"
JUMPS="walker-sv"
TUNNEL_PID=""

cleanup() {
  if [ -n "${TUNNEL_PID:-}" ]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
    wait "$TUNNEL_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$TARGET" || { echo "找不到 $TARGET"; exit 1; }

echo "当前版本：$(git rev-parse --short HEAD)  $(git log -1 --format=%s | cut -c1-40)"
echo

# 先试直连，8 秒不通就借道
if curl -s -o /dev/null -m 8 https://github.com; then
  echo "GitHub 直连可用，直接拉取"
  git pull --ff-only
else
  echo "GitHub 直连不通，借道 $JUMPS"
  ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -D 127.0.0.1:1080 "$JUMPS" >/dev/null 2>&1 &
  TUNNEL_PID=$!
  sleep 1
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "借道失败：SSH 隧道未能建立"
    exit 1
  fi
  git -c http.proxy=socks5h://127.0.0.1:1080 \
      -c https.proxy=socks5h://127.0.0.1:1080 pull --ff-only
fi

echo
echo "现在版本：$(git rev-parse --short HEAD)  $(git log -1 --format=%s | cut -c1-40)"
git status --porcelain | head -5
