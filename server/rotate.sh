#!/bin/bash
# 一键更换订阅 token：旧链接立刻失效
# 事务化：先备份 → 全部改在临时文件 → 校验 → 原子替换 → reload；任何一步失败自动回滚
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

BAK=$(mktemp -d)
cp "$CADDY" "$BAK/Caddyfile"
cp "$WEB/index.html" "$BAK/index.html"
restore() {
  echo "回滚：恢复原配置"
  cp "$BAK/Caddyfile" "$CADDY"
  cp "$BAK/index.html" "$WEB/index.html"
  systemctl reload caddy >/dev/null 2>&1 || true
  rm -rf "$BAK"
}
trap restore ERR

cp "$WEB/index.html" "$WEB/index.html.new"
sed -i "s|$OLDSUB|$NEWSUB|g; s|$OLD64|$NEW64|g; s|$OLDENC|$NEWENC|g" "$WEB/index.html.new"
cp "$CADDY" "$BAK/Caddyfile.new"
sed -i "s|/s/$OLD|/s/$NEW|g" "$BAK/Caddyfile.new"
qrencode -o "$WEB/qr-sub.png.new" -s 12 -m 2 "$NEWSUB"

caddy validate --config "$BAK/Caddyfile.new" --adapter caddyfile >/dev/null

mv "$WEB/index.html.new" "$WEB/index.html"
mv "$WEB/qr-sub.png.new" "$WEB/qr-sub.png"
mv "$BAK/Caddyfile.new" "$CADDY"
systemctl reload caddy

trap - ERR
rm -rf "$BAK"

echo "已换锁。旧 token: $OLD 已失效"
echo "新订阅地址: $NEWSUB"
