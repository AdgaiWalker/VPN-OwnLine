#!/usr/bin/env bash
# ==============================================================================
# Evergreen OwnLine · 自定义域名绑定与切换助手
#
# 用法：
#   sudo bash /opt/web/change_domain.sh <新域名> [--skip-dns-check]
# ==============================================================================
set -euo pipefail

say()  { printf '\n==> %s\n' "$*"; }
ok()   { printf '  [ok] %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*"; }
die()  { printf '\n[err] %s\n' "$*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS="${LADDER_SETTINGS:-/opt/web-data/settings.json}"
CADDYFILE="${LADDER_CADDYFILE:-/etc/caddy/Caddyfile}"
QR_OUT="${LADDER_QR_OUT:-/opt/web/qr-sub.png}"

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
  printf '请输入你想绑定的新域名 (例如 vpn.yourdomain.com): '
  read -r NEW_DOMAIN
fi

NEW_DOMAIN=$(echo "$NEW_DOMAIN" | tr 'A-Z' 'a-z' | xargs)
[[ "$NEW_DOMAIN" =~ ^[a-z0-9][a-z0-9.-]{0,251}[a-z0-9]$ ]] || die "域名格式不正确: $NEW_DOMAIN"

[ -f "$SETTINGS" ] || die "未找到 $SETTINGS，请确认系统已完成首次安装。"
[ -f "$CADDYFILE" ] || die "未找到 $CADDYFILE，请确认 Caddy 已配置。"

say "1/4 正在获取本机公网 IP 并校验 DNS 解析..."
if [ "$SKIP_DNS" = 0 ]; then
  PUB_IP=$(curl -fsSL --connect-timeout 4 https://api.ipify.org 2>/dev/null || curl -fsSL --connect-timeout 4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
  [ -n "$PUB_IP" ] || die "无法获取本机公网 IP，请检查服务器网络。"
  ok "本机公网 IP: $PUB_IP"

  RESOLVED_IP=$(getent ahostsv4 "$NEW_DOMAIN" 2>/dev/null | awk '{print $1}' | head -n 1 || true)
  if [ "$RESOLVED_IP" != "$PUB_IP" ]; then
    warn "域名解析未就绪！"
    echo "  域名: $NEW_DOMAIN"
    echo "  当前解析到的 IP: ${RESOLVED_IP:-未解析}"
    echo "  服务器真实 IP:   $PUB_IP"
    echo ""
    echo "请前往你的域名 DNS 控制台（如 Cloudflare / 腾讯云 / 阿里云）："
    echo "1. 添加一条 A 记录，将 '$NEW_DOMAIN' 指向 '$PUB_IP'"
    echo "2. 若使用 Cloudflare 且直接代理到本机端口，请核对代理模式（灰色云直连）"
    echo "3. 生效后重试；若已确认解析生效，可加 --skip-dns-check 执行。"
    exit 1
  fi
  ok "DNS 解析已验证通过 ($NEW_DOMAIN -> $PUB_IP)"
else
  ok "已按 --skip-dns-check 跳过 DNS 解析检查"
fi

say "2/4 正在渲染新 Caddyfile 并验证配置..."
CADDY_DIR="$(dirname "$CADDYFILE")"
CADDY_TMP="$(mktemp "${CADDY_DIR}/.caddyfile-new-XXXXXX")"
cleanup_tmp() { rm -f "$CADDY_TMP"; }
trap cleanup_tmp EXIT

python3 - "$CADDYFILE" "$CADDY_TMP" "$NEW_DOMAIN" <<'PY'
import re
import sys

source, target, new_domain = sys.argv[1], sys.argv[2], sys.argv[3]
with open(source, "r", encoding="utf-8") as f:
    text = f.read()

text = re.sub(r"https://[a-zA-Z0-9.-]+:8443\s*\{", f"https://{new_domain}:8443 {{", text)

with open(target, "w", encoding="utf-8") as f:
    f.write(text)
PY

if ! caddy validate --config "$CADDY_TMP" --adapter caddyfile >/dev/null 2>&1; then
  die "Caddy 配置文件验证失败，原配置未做任何修改。"
fi

if getent group caddy >/dev/null 2>&1; then
  chown root:caddy "$CADDY_TMP"
fi
chmod 640 "$CADDY_TMP"
cp -f "$CADDYFILE" "${CADDYFILE}.bak-$(date +%Y%m%d%H%M%S)"
mv -f "$CADDY_TMP" "$CADDYFILE"
ok "Caddy 配置文件已按 0640 最小权限原子更新，原配置已备份"

say "3/4 正在平滑重载 Caddy..."
systemctl reload caddy
ok "Caddy 已热重载"

say "4/4 正在持锁原子更新系统订阅配置..."
SETTINGS_OUT=$(
  PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$SETTINGS" "$NEW_DOMAIN" <<'PY'
import os
import sys

from nodekit.store import AtomicJsonStore

settings_path, new_domain = sys.argv[1], sys.argv[2]


def _mutate(current):
    data = dict(current) if isinstance(current, dict) else {}
    data["domain"] = new_domain
    return data


updated = AtomicJsonStore.update(settings_path, _mutate, default={})
os.chmod(settings_path, 0o600)
sub_token = str(updated.get("sub_token", "") or "")
sub_port = str(updated.get("sub_port", "") or "")
print(sub_token)
print(sub_port)
PY
)
SUB_TOKEN="$(printf '%s\n' "$SETTINGS_OUT" | sed -n '1p')"
SUB_PORT="$(printf '%s\n' "$SETTINGS_OUT" | sed -n '2p')"

PORT_PART=""
if [ -n "$SUB_PORT" ] && [ "$SUB_PORT" != "443" ] && [ "$SUB_PORT" != "80" ]; then
  PORT_PART=":$SUB_PORT"
fi
NEW_SUB="https://${NEW_DOMAIN}${PORT_PART}/s/${SUB_TOKEN}"

if [ -n "$SUB_TOKEN" ] && command -v qrencode >/dev/null 2>&1; then
  qrencode -o "$QR_OUT" -s 12 -m 2 "$NEW_SUB" 2>/dev/null || true
fi
ok "系统订阅地址已安全切换为新域名"

say "域名绑定完成"
echo "  新管理控制台: https://${NEW_DOMAIN}:8443/"
echo "  新订阅分发地址: $NEW_SUB"
