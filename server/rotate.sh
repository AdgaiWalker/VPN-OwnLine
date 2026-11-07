#!/bin/bash
# 命令行换锁：生成 256-bit 订阅 Token，原子更新 settings.json (0600) 并刷新二维码
# 订阅由 admin.py 动态处理，无需修改或 reload Caddyfile
set -euo pipefail

SETTINGS="${LADDER_SETTINGS:-/opt/web-data/settings.json}"
[ -f "$SETTINGS" ] || { echo "错误: $SETTINGS 不存在" >&2; exit 1; }

NEW="$(openssl rand -hex 32)"
python3 - "$SETTINGS" "$NEW" <<'PY'
import json, os, sys, tempfile
path, token = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
data["sub_token"] = token
fd, tmp = tempfile.mkstemp(prefix=".ownline-", dir=os.path.dirname(path) or ".")
try:
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
finally:
    if os.path.exists(tmp):
        os.unlink(tmp)
PY

DOMAIN="$(python3 - "$SETTINGS" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("domain", "localhost") or "localhost")
PY
)"
PORT="$(python3 - "$SETTINGS" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get("sub_port", ""))
PY
)"
PORT_PART=""
if [ -n "$PORT" ] && [ "$PORT" != "443" ] && [ "$PORT" != "80" ]; then
  PORT_PART=":$PORT"
fi
NEWSUB="https://${DOMAIN}${PORT_PART}/s/$NEW"

if command -v qrencode >/dev/null 2>&1; then
  qrencode -o /opt/web/qr-sub.png -s 12 -m 2 "$NEWSUB" 2>/dev/null || true
fi

echo "已换锁。新订阅地址: $NEWSUB"
