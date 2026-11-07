#!/usr/bin/env bash
# ==============================================================================
# 长青 (Evergreen OwnLine) · Cloudflare DDNS 自动解析与中枢漫游工具
#
# 哲学：
#   母机漂移，专线长青。
#   当主控服务器更换 IP 或迁移新主机时，自动将 Cloudflare DNS A 记录更新为本机最新公网 IP。
#   手机小火箭 / Clash 订阅域名保持永久不变，实现 100% 零感自动化漫游。
#
# 用法：
#   sudo bash /opt/web/cf_ddns.sh --token <CF_API_TOKEN> --zone-id <ZONE_ID> --domain <DOMAIN>
#   或者将配置写入 /opt/web-data/cf_settings.json 后直接执行：
#   sudo bash /opt/web/cf_ddns.sh
# ==============================================================================
set -euo pipefail

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✖ %s\033[0m\n' "$*" >&2; exit 1; }

CF_CONFIG="/opt/web-data/cf_settings.json"
CF_TOKEN=""
CF_ZONE_ID=""
CF_DOMAIN=""
DRY_RUN=0

# 从配置文件预读
if [ -f "$CF_CONFIG" ]; then
  CF_TOKEN=$(python3 -c "import json; print(json.load(open('$CF_CONFIG')).get('token', ''))" 2>/dev/null || true)
  CF_ZONE_ID=$(python3 -c "import json; print(json.load(open('$CF_CONFIG')).get('zone_id', ''))" 2>/dev/null || true)
  CF_DOMAIN=$(python3 -c "import json; print(json.load(open('$CF_CONFIG')).get('domain', ''))" 2>/dev/null || true)
fi

while [ $# -gt 0 ]; do
  case "$1" in
    --token)
      CF_TOKEN="$2"; shift 2 ;;
    --zone-id)
      CF_ZONE_ID="$2"; shift 2 ;;
    --domain)
      CF_DOMAIN="$2"; shift 2 ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    --help|-h)
      echo "用法: sudo bash $0 [--token <TOKEN>] [--zone-id <ZONE_ID>] [--domain <DOMAIN>] [--dry-run]"
      exit 0 ;;
    *)
      die "未知参数: $1" ;;
  esac
done

[ -n "$CF_TOKEN" ] || die "缺少 Cloudflare API Token（请通过 --token 指定或存入 $CF_CONFIG）"
[ -n "$CF_ZONE_ID" ] || die "缺少 Cloudflare Zone ID（请通过 --zone-id 指定或存入 $CF_CONFIG）"
[ -n "$CF_DOMAIN" ] || die "缺少目标域名（请通过 --domain 指定或存入 $CF_CONFIG）"

say "1/3 获取本机公网 IPv4..."
PUB_IP=""
for url in "https://api.ipify.org" "https://ifconfig.me" "https://icanhazip.com"; do
  PUB_IP=$(curl -fsSL --connect-timeout 4 "$url" 2>/dev/null | tr -d ' \n\r' || true)
  if [[ "$PUB_IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
    break
  fi
done
[ -n "$PUB_IP" ] || die "无法获取本机公网 IP，请检查服务器网络。"
ok "本机公网 IP: $PUB_IP"

say "2/3 查询 Cloudflare 现有 DNS A 记录 ($CF_DOMAIN)..."
CF_API="https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records"
RESP=$(curl -sSL -X GET "${CF_API}?name=${CF_DOMAIN}&type=A" \
  -H "Authorization: Bearer ${CF_TOKEN}" \
  -H "Content-Type: application/json")

IS_SUCCESS=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('success', False))" "$RESP" 2>/dev/null || echo "False")
if [ "$IS_SUCCESS" != "True" ]; then
  ERR_MSG=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('errors', []))" "$RESP" 2>/dev/null || echo "API error")
  die "Cloudflare API 查询失败: $ERR_MSG"
fi

RECORD_ID=$(python3 -c "import sys, json; res = json.loads(sys.argv[1]).get('result', []); print(res[0]['id'] if res else '')" "$RESP")
CURRENT_IP=$(python3 -c "import sys, json; res = json.loads(sys.argv[1]).get('result', []); print(res[0]['content'] if res else '')" "$RESP")

if [ -n "$RECORD_ID" ] && [ "$CURRENT_IP" = "$PUB_IP" ]; then
  ok "DNS 解析已指向本机 IP ($CF_DOMAIN -> $PUB_IP)，无需更新"
  exit 0
fi

say "3/3 同步更新 Cloudflare DNS 记录..."
if [ "$DRY_RUN" = 1 ]; then
  ok "演练模式：跳过写入，目标更新为 $CF_DOMAIN -> $PUB_IP"
  exit 0
fi

if [ -n "$RECORD_ID" ]; then
  # 更新已有记录 (PUT)
  UPDATE_RESP=$(curl -sSL -X PUT "${CF_API}/${RECORD_ID}" \
    -H "Authorization: Bearer ${CF_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{\"type\":\"A\",\"name\":\"${CF_DOMAIN}\",\"content\":\"${PUB_IP}\",\"ttl\":120,\"proxied\":false}")
else
  # 创建新记录 (POST)
  UPDATE_RESP=$(curl -sSL -X POST "${CF_API}" \
    -H "Authorization: Bearer ${CF_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "{\"type\":\"A\",\"name\":\"${CF_DOMAIN}\",\"content\":\"${PUB_IP}\",\"ttl\":120,\"proxied\":false}")
fi

IS_UPDATED=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('success', False))" "$UPDATE_RESP" 2>/dev/null || echo "False")
if [ "$IS_UPDATED" != "True" ]; then
  ERR_MSG=$(python3 -c "import sys, json; print(json.loads(sys.argv[1]).get('errors', []))" "$UPDATE_RESP" 2>/dev/null || echo "Update error")
  die "Cloudflare DNS 写入失败: $ERR_MSG"
fi

ok "Cloudflare DNS 记录同步成功: $CF_DOMAIN -> $PUB_IP (proxied: false)"
