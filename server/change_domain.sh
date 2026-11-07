#!/usr/bin/env bash
# ==============================================================================
# 长青 (Evergreen OwnLine) · 自定义域名绑定与切换助手
#
# 哲学：
#   零摩擦演化：先用默认 sslip.io 跑通，有了自有域名随时平滑切换。
#   平滑热更新：自动校验 DNS、自动申请新 SSL 证书、自动更新订阅地址，
#   不重启代理进程，不影响现有节点流量。
#
# 用法：
#   sudo bash /opt/web/change_domain.sh [新域名] [--skip-dns-check]
#   例如：
#   sudo bash /opt/web/change_domain.sh vpn.yourdomain.com
# ==============================================================================
set -euo pipefail

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✖ %s\033[0m\n' "$*" >&2; exit 1; }

NEW_DOMAIN=""
SKIP_DNS=0

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-dns-check)
      SKIP_DNS=1; shift ;;
    --help|-h)
      echo "用法: sudo bash $0 <新域名> [--skip-dns-check]"
      echo "示例: sudo bash $0 vpn.yourdomain.com"
      exit 0 ;;
    -*)
      die "未知参数: $1" ;;
    *)
      if [ -z "$NEW_DOMAIN" ]; then
        NEW_DOMAIN="$1"
      else
        die "冗余参数: $1"
      fi
      shift ;;
  esac
done

if [ "$(id -u)" != "0" ]; then
  die "请用 root 权限执行此脚本 (sudo bash $0)"
fi

if [ -z "$NEW_DOMAIN" ]; then
  printf '👉 请输入你想绑定的新域名 (例如 vpn.yourdomain.com): '
  read -r NEW_DOMAIN
fi

NEW_DOMAIN=$(echo "$NEW_DOMAIN" | tr 'A-Z' 'a-z' | xargs)
[[ "$NEW_DOMAIN" =~ ^[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]$ ]] || die "域名格式不正确: $NEW_DOMAIN"

SETTINGS="/opt/web-data/settings.json"
CADDYFILE="/etc/caddy/Caddyfile"

[ -f "$SETTINGS" ] || die "未找到 $SETTINGS，请确认系统已完成首次安装。"
[ -f "$CADDYFILE" ] || die "未找到 $CADDYFILE，请确认 Caddy 已配置。"

say "1/4 正在获取本机公网 IP 并校验 DNS 解析..."
PUB_IP=$(curl -fsSL --connect-timeout 4 https://api.ipify.org 2>/dev/null || curl -fsSL --connect-timeout 4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
[ -n "$PUB_IP" ] || die "无法获取本机公网 IP，请检查服务器网络。"
ok "本机公网 IP: $PUB_IP"

if [ "$SKIP_DNS" = 0 ]; then
  RESOLVED_IP=$(getent ahostsv4 "$NEW_DOMAIN" 2>/dev/null | awk '{print $1}' | head -n 1 || true)
  if [ "$RESOLVED_IP" != "$PUB_IP" ]; then
    warn "域名解析未就绪！"
    echo "  域名: $NEW_DOMAIN"
    echo "  当前解析到的 IP: ${RESOLVED_IP:-未解析}"
    echo "  服务器真实 IP:   $PUB_IP"
    echo ""
    echo "请前往你的域名 DNS 控制台（如 Cloudflare / 腾讯云 / 阿里云）："
    echo "1. 添加一条 A 记录，将 '$NEW_DOMAIN' 指向 '$PUB_IP'"
    echo "2. ⚠️ 若使用 Cloudflare，务必关闭橙色小云朵（设置为 DNS only / 灰色云），否则证书申请与代理握手会被拦截"
    echo "3. 等待 1~2 分钟生效后重试。若已确认解析生效，可加 --skip-dns-check 强制执行。"
    exit 1
  fi
  ok "DNS 解析已验证通过 ($NEW_DOMAIN -> $PUB_IP)"
fi

say "2/4 正在渲染新 Caddyfile 并验证配置..."
CADDY_TMP="$(mktemp /etc/caddy/.caddyfile-new-XXXXXX)"

# 替换 Caddyfile 中的域名绑定
python3 - "$CADDYFILE" "$CADDY_TMP" "$NEW_DOMAIN" <<'PY'
import sys, re
source, target, new_domain = sys.argv[1], sys.argv[2], sys.argv[3]
with open(source, 'r', encoding='utf-8') as f:
    text = f.read()

# 替换 https://<domain>:8443
text = re.sub(r'https://[a-zA-Z0-9.-]+:8443\s*\{', f'https://{new_domain}:8443 {{', text)
# 替换 :80 中的重定向目标
text = re.sub(r'redir https://[a-zA-Z0-9.-]+:8443\{uri\} 308', f'redir https://{new_domain}:8443{{uri}} 308', text)

with open(target, 'w', encoding='utf-8') as f:
    f.write(text)
PY

if ! caddy validate --config "$CADDY_TMP" --adapter caddyfile >/dev/null 2>&1; then
  rm -f "$CADDY_TMP"
  die "Caddy 配置文件验证失败，原配置未做任何修改。"
fi

cp -f "$CADDYFILE" "${CADDYFILE}.bak-$(date +%Y%m%d%H%M%S)"
mv -f "$CADDY_TMP" "$CADDYFILE"
chmod 644 "$CADDYFILE"
ok "Caddy 配置文件已更新，原配置已备份"

say "3/4 正在平滑重载 Caddy 并自动申请新证书..."
systemctl reload caddy
ok "Caddy 已热重载，证书正在自动签发中"

say "4/4 正在更新系统订阅配置..."
python3 -c "
import json
with open('$SETTINGS', 'r') as f:
    s = json.load(f)
s['domain'] = '$NEW_DOMAIN'
with open('$SETTINGS', 'w') as f:
    json.dump(s, f, indent=2)
"

# 如果有二维码，重新生成
SUB_TOKEN=$(python3 -c "import json; print(json.load(open('$SETTINGS')).get('sub_token', ''))")
SUB_PORT=$(python3 -c "import json; print(json.load(open('$SETTINGS')).get('sub_port', 8443))")
PORT_PART=""
if [ -n "$SUB_PORT" ] && [ "$SUB_PORT" != "443" ] && [ "$SUB_PORT" != "80" ]; then
  PORT_PART=":$SUB_PORT"
fi
NEW_SUB="https://${NEW_DOMAIN}${PORT_PART}/s/${SUB_TOKEN}"

if command -v qrencode >/dev/null 2>&1; then
  qrencode -o /opt/web/qr-sub.png -s 12 -m 2 "$NEW_SUB" 2>/dev/null || true
fi
ok "系统订阅地址已自动切换为新域名"

say "🎉 域名绑定成功！"
echo ""
printf '  \033[1;32m👉 新管理控制台: https://%s:8443/\033[0m\n' "$NEW_DOMAIN"
printf '  \033[1;32m👉 新订阅分发地址: %s\033[0m\n' "$NEW_SUB"
echo ""
echo "客户端（小火箭 / Clash）下次刷新订阅时将自动使用新域名通信。"
