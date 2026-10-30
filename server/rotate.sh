#!/bin/bash
# 命令行换锁：更新 settings.json 并重新生成二维码
# 订阅由 admin.py 动态处理，无需修改或 reload Caddyfile
set -euo pipefail

SETTINGS=/opt/web-data/settings.json
[ -f "$SETTINGS" ] || { echo "错误: $SETTINGS 不存在"; exit 1; }

NEW=$(openssl rand -hex 5)
python3 -c "import json; s=json.load(open('$SETTINGS')); s['sub_token']='$NEW'; json.dump(s, open('$SETTINGS','w'), indent=2)"
DOMAIN=$(python3 -c "import json; print(json.load(open('$SETTINGS')).get('domain', ''))")
PORT=$(python3 -c "import json; print(json.load(open('$SETTINGS')).get('sub_port', 8443))")
PORT_PART=""
if [ -n "$PORT" ] && [ "$PORT" != "443" ] && [ "$PORT" != "80" ]; then
  PORT_PART=":$PORT"
fi
NEWSUB="https://${DOMAIN}${PORT_PART}/s/$NEW"

if command -v qrencode >/dev/null 2>&1; then
  qrencode -o /opt/web/qr-sub.png -s 12 -m 2 "$NEWSUB" 2>/dev/null || true
fi

echo "已换锁。新 token: $NEW"
echo "新订阅地址: $NEWSUB"
