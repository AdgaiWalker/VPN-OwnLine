#!/bin/bash
# 命令行换锁：生成 256-bit 订阅 Token，持排他文件锁原子更新 settings.json (0600) 并刷新二维码
# 订阅由 admin.py 动态处理，无需修改或 reload Caddyfile
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${LADDER_SETTINGS:-/opt/web-data/settings.json}"
QR_OUT="${LADDER_QR_OUT:-/opt/web/qr-sub.png}"
[ -f "$SETTINGS" ] || { echo "错误: $SETTINGS 不存在" >&2; exit 1; }

NEW="$(openssl rand -hex 32)"
SETTINGS_META=$(
  PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$SETTINGS" "$NEW" <<'PY'
import os
import sys

from nodekit.store import AtomicJsonStore

settings_path, token = sys.argv[1], sys.argv[2]


def _mutate(current):
    data = dict(current) if isinstance(current, dict) else {}
    data["sub_token"] = token
    return data


updated = AtomicJsonStore.update(settings_path, _mutate, default={})
os.chmod(settings_path, 0o600)
domain = str(updated.get("domain", "localhost") or "localhost")
port = str(updated.get("sub_port", "") or "")
print(domain)
print(port)
PY
)
DOMAIN="$(printf '%s\n' "$SETTINGS_META" | sed -n '1p')"
PORT="$(printf '%s\n' "$SETTINGS_META" | sed -n '2p')"

PORT_PART=""
if [ -n "$PORT" ] && [ "$PORT" != "443" ] && [ "$PORT" != "80" ]; then
  PORT_PART=":$PORT"
fi
NEWSUB="https://${DOMAIN}${PORT_PART}/s/$NEW"

if command -v qrencode >/dev/null 2>&1; then
  qrencode -o "$QR_OUT" -s 12 -m 2 "$NEWSUB" 2>/dev/null || true
fi

echo "已换锁。新订阅地址: $NEWSUB"
