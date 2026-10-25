#!/bin/bash
# 一键更换订阅 token：旧链接立刻失效
set -euo pipefail
CADDY=/etc/caddy/Caddyfile
WEB=/opt/web
HOST=v.example.com

OLD=$(grep -oP '(?<=/s/)[0-9a-f]{10}' "$CADDY" | head -1)
if [ -z "${OLD:-}" ]; then echo "找不到当前 token，退出"; exit 1; fi
NEW=$(openssl rand -hex 5)
OLDSUB="https://$HOST/s/$OLD"
NEWSUB="https://$HOST/s/$NEW"

enc() { python3 -c 'import urllib.parse,sys;print(urllib.parse.quote(sys.argv[1],safe=""))' "$1"; }
OLD64=$(printf %s "$OLDSUB" | base64 -w0)
NEW64=$(printf %s "$NEWSUB" | base64 -w0)
OLDENC=$(enc "$OLDSUB")
NEWENC=$(enc "$NEWSUB")

sed -i "s|$OLDSUB|$NEWSUB|g; s|$OLD64|$NEW64|g; s|$OLDENC|$NEWENC|g" "$WEB/index.html"
qrencode -o "$WEB/qr-sub.png" -s 12 -m 2 "$NEWSUB"
sed -i "s|/s/$OLD|/s/$NEW|g" "$CADDY"
caddy validate --config "$CADDY" --adapter caddyfile >/dev/null
systemctl reload caddy

echo "已换锁。旧 token: $OLD 已失效"
echo "新订阅地址: $NEWSUB"
