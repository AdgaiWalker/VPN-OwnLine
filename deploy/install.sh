#!/usr/bin/env bash
# 一键部署：把本机器安装为 Ladder 翻墙主控 + 本地出口节点
#
# 用法：
#   sudo ./deploy/install.sh [选项]
#
# 选项：
#   --domain, -d <域名>    指定自有域名（未指定时自动采用 <ip>.sslip.io 免域名申请正式证书）
#   --tls-internal        强制 Caddy 使用内置自签证书（适用于 Cloudflare 代理或测试环境）
#   --dry-run             演练模式：仅打印步骤，不实际修改系统
#   --uninstall           停止并清理 ladder 系统服务
#   --purge               搭配 --uninstall 使用，连同配置与数据一并删除
#
# 前置条件：
#   - 必须运行于可直连海外网络的海外机器（主控）
#   - Debian 12+ / Ubuntu 22.04+，具有 root 权限与 systemd
set -euo pipefail

SINGBOX_VERSION="1.14.4"
SHA256_AMD64="699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968"
SHA256_ARM64="436441f76ee2f7fe21b5b2d426d3cb261a480455a704865789ad533e4273ec26"

DOMAIN=""
TLS_INTERNAL=0
DRY_RUN=0
UNINSTALL=0
PURGE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --domain|-d)
      DOMAIN="$2"; shift 2 ;;
    --tls-internal)
      TLS_INTERNAL=1; shift ;;
    --dry-run)
      DRY_RUN=1; shift ;;
    --uninstall)
      UNINSTALL=1; shift ;;
    --purge)
      PURGE=1; shift ;;
    -*)
      echo "未知参数: $1" >&2; exit 1 ;;
    *)
      if [ -z "$DOMAIN" ]; then DOMAIN="$1"; else echo "冗余参数: $1" >&2; exit 1; fi
      shift ;;
  esac
done

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY_RUN" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }

# ---------- 卸载逻辑 ----------
if [ "$UNINSTALL" = 1 ]; then
  say "正在卸载 Ladder 服务..."
  SERVICES="admin.service sing-box.service probe.timer probe.service usage-refresh.timer usage-refresh.service ipcheck.timer ipcheck.service backup-remote.timer backup-remote.service"
  for s in $SERVICES; do
    systemctl stop "$s" 2>/dev/null || true
    systemctl disable "$s" 2>/dev/null || true
    rm -f "/etc/systemd/system/$s"
  done
  systemctl daemon-reload 2>/dev/null || true
  ok "系统服务已停止并清理"

  if [ "$PURGE" = 1 ]; then
    rm -rf /opt/web /opt/web-data /opt/sing-box /etc/caddy/Caddyfile
    ok "已彻底清除数据与配置目录 (--purge)"
  else
    warn "配置与数据仍保存在 /opt/web-data，如需彻底清除请加 --purge"
  fi
  exit 0
fi

# ---------- 0. 前置检查 ----------
say "0/10 预检运行环境"
[ "$(id -u)" = "0" ] || die "必须使用 root 权限运行: sudo $0"
[ -d /run/systemd/system ] || die "系统缺少 systemd 支持"
command -v apt-get >/dev/null 2>&1 || die "目前仅支持 Debian / Ubuntu 系统 (apt-get)"

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  SB_ARCH=amd64; EXPECTED_SHA="$SHA256_AMD64" ;;
  aarch64) SB_ARCH=arm64; EXPECTED_SHA="$SHA256_ARM64" ;;
  *) die "不支持的 CPU 架构: $ARCH (仅支持 x86_64 与 aarch64)" ;;
esac
ok "CPU 架构: $ARCH"

FREE_MB=$(df -m / | awk 'NR==2 {print $4}')
[ "${FREE_MB:-0}" -ge 500 ] || die "磁盘可用空间不足: 剩余 ${FREE_MB:-0}MB，至少需要 500MB"
ok "磁盘空间充裕: 剩余 ${FREE_MB}MB"

# 海外直连预检
if [ "$DRY_RUN" = 0 ]; then
  if ! curl -fsSL --connect-timeout 4 https://www.google.com/generate_204 >/dev/null 2>&1 && \
     ! curl -fsSL --connect-timeout 4 https://cloudflare.com/cdn-cgi/trace >/dev/null 2>&1; then
    die "本机无法直连海外网络！第一台机器（主控）必须在海外。请先在海外 VPS 上部署主控！"
  fi
  ok "海外直连网络正常"
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
if [ -f "$REPO/server/admin.py" ]; then
  SRC_SERVER="$REPO/server"
  SRC_WEB="$REPO/web"
  SRC_DEPLOY="$REPO/deploy"
elif [ -f "./server/admin.py" ]; then
  SRC_SERVER="./server"
  SRC_WEB="./web"
  SRC_DEPLOY="./deploy"
elif [ -f "/opt/web/admin.py" ]; then
  SRC_SERVER="/opt/web"
  SRC_WEB="/opt/web"
  SRC_DEPLOY="/opt/web/deploy"
else
  die "找不到 ladder 源代码（server/admin.py），请在克隆的仓库目录下运行 ./deploy/install.sh"
fi
ok "源码目录确认: $SRC_SERVER"
[ "$DRY_RUN" = 1 ] && warn "当前处于 dry-run 模式：只打印，不执行实际系统变更"

# ---------- 1. 系统依赖 ----------
say "1/10 安装系统依赖 (python3 / curl / openssl / qrencode / caddy)"
run apt-get update -qq
run apt-get install -y -qq curl openssl ca-certificates python3 gnupg debian-keyring debian-archive-keyring apt-transport-https qrencode

if ! command -v caddy >/dev/null 2>&1; then
  ok "从官方源安装 Caddy"
  if [ "$DRY_RUN" = 0 ]; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy
  fi
else
  ok "Caddy 已就位: $(caddy version 2>/dev/null | head -1)"
fi

# ---------- 2. sing-box 安装与校验 ----------
say "2/10 安装并校验 sing-box $SINGBOX_VERSION"
if [ -x /opt/sing-box/sing-box ]; then
  ok "sing-box 已存在: $(/opt/sing-box/sing-box version 2>/dev/null | head -1)"
else
  URL="https://github.com/SagerNet/sing-box/releases/download/v$SINGBOX_VERSION/sing-box-$SINGBOX_VERSION-linux-$SB_ARCH.tar.gz"
  run mkdir -p /opt/sing-box
  if [ "$DRY_RUN" = 0 ]; then
    curl -fsSL -o /tmp/sb.tgz "$URL" || die "下载 sing-box 失败: $URL"
    ACTUAL_SHA=$(sha256sum /tmp/sb.tgz | awk '{print $1}')
    if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
      rm -f /tmp/sb.tgz
      die "sing-box 校验和不匹配！期望: $EXPECTED_SHA，实际: $ACTUAL_SHA"
    fi
    tar xzf /tmp/sb.tgz -C /opt/sing-box --strip-components=1
    rm -f /tmp/sb.tgz
  fi
  ok "sing-box $SINGBOX_VERSION 校验通过并安装成功"
fi

# ---------- 3. 代码与数据目录部署 ----------
say "3/10 部署代码到 /opt/web 与 /opt/web-data"
run mkdir -p /opt/web /opt/web-data
run chmod 700 /opt/web-data
if [ "$SRC_SERVER" != "/opt/web" ]; then
  if [ -d "$SRC_SERVER/providers" ]; then run cp -r "$SRC_SERVER/providers" /opt/web/; fi
  if [ -d "$SRC_SERVER/nodekit" ]; then run cp -r "$SRC_SERVER/nodekit" /opt/web/; fi
  run cp "$SRC_SERVER"/*.py /opt/web/ 2>/dev/null || true
  run cp "$SRC_SERVER"/*.sh /opt/web/ 2>/dev/null || true
  if [ -f "$SRC_WEB/index.html" ]; then run cp "$SRC_WEB/index.html" /opt/web/; fi
  run chmod 755 /opt/web/*.sh /opt/web/*.py 2>/dev/null || true
fi
ok "代码与脚本部署完成"

# ---------- 4. 确定公网 IP 与域名 ----------
say "4/10 确定公网 IP 与服务域名"
PUB_IP=""
if [ "$DRY_RUN" = 0 ]; then
  PUB_IP=$(curl -fsSL --connect-timeout 4 https://api.ipify.org 2>/dev/null || curl -fsSL --connect-timeout 4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
else
  PUB_IP="198.51.100.12"
fi
[ -n "$PUB_IP" ] || die "无法获取本机公网 IP"
ok "本机公网 IP: $PUB_IP"

if [ -z "$DOMAIN" ]; then
  DASH_IP=$(echo "$PUB_IP" | tr '.' '-')
  DOMAIN="${DASH_IP}.sslip.io"
  ok "未显式指定域名，自动采用 sslip.io: $DOMAIN"
else
  ok "使用指定域名: $DOMAIN"
fi

# ---------- 5. 生成本机双协议出口节点 (Reality + Hysteria2) ----------
say "5/10 生成并校验本机出口节点配置"
SINGBOX_BIN="/opt/sing-box/sing-box"

if [ -f /opt/sing-box/config.json ]; then
  warn "/opt/sing-box/config.json 已存在，保留现有节点配置"
else
  if [ "$DRY_RUN" = 0 ]; then
    UUID=$("$SINGBOX_BIN" generate uuid | tr -d '[:space:]')
    KP=$("$SINGBOX_BIN" generate reality-keypair)
    PRIV=$(echo "$KP" | grep "PrivateKey:" | awk '{print $2}' | tr -d '[:space:]')
    PBK=$(echo "$KP" | grep "PublicKey:" | awk '{print $2}' | tr -d '[:space:]')
    SID=$(openssl rand -hex 4)
    HY2_PASS=$(openssl rand -hex 12)
    HY2_OBFS=$(openssl rand -hex 8)

    openssl req -x509 -nodes -newkey rsa:2048 -keyout /opt/sing-box/hy2.key -out /opt/sing-box/hy2.crt -days 3650 -subj "/CN=www.bing.com" 2>/dev/null
    chmod 600 /opt/sing-box/hy2.key

    python3 - << 'PYGEN'
import sys, json
sys.path.insert(0, "/opt/web")
from nodekit import templates

import os
uuid = os.environ["UUID"]
priv = os.environ["PRIV"]
pbk = os.environ["PBK"]
sid = os.environ["SID"]
hy2_pass = os.environ["HY2_PASS"]
hy2_obfs = os.environ["HY2_OBFS"]

hy2_opts = {
    "port": 443,
    "password": hy2_pass,
    "obfs_password": hy2_obfs,
    "sni": "www.bing.com",
    "cert_path": "/opt/sing-box/hy2.crt",
    "key_path": "/opt/sing-box/hy2.key"
}
cfg = templates.exit_config(443, uuid, "www.apple.com", priv, sid, hy2=hy2_opts)
errs = templates.validate(cfg)
if errs:
    sys.stderr.write("配置校验失败: " + ",".join(errs) + "\n")
    sys.exit(1)
with open("/tmp/sb_init.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
PYGEN
    "$SINGBOX_BIN" check -c /tmp/sb_init.json || die "sing-box check 失败，配置无效"
    mv /tmp/sb_init.json /opt/sing-box/config.json
    ok "sing-box 本地双协议配置已生成"

    # 初始化 nodes.json
    INITIAL_NODES=$(python3 - << 'PYNODES'
import json, os
ip = os.environ["PUB_IP"]
nodes = [
    {
        "name": "主控-出口",
        "host": ip,
        "port": 443,
        "uuid": os.environ["UUID"],
        "sni": "www.apple.com",
        "pbk": os.environ["PBK"],
        "sid": os.environ["SID"],
        "role": "exit",
        "source": "builtin",
        "local": True,
        "health": "unknown"
    },
    {
        "name": "主控-出口-HY2",
        "type": "hysteria2",
        "host": ip,
        "port": 443,
        "password": os.environ["HY2_PASS"],
        "sni": "www.bing.com",
        "obfs_password": os.environ["HY2_OBFS"],
        "role": "exit",
        "source": "builtin",
        "local": True,
        "health": "unknown"
    }
]
print(json.dumps(nodes, ensure_ascii=False, indent=2))
PYNODES
)
    if [ ! -f /opt/web-data/nodes.json ]; then
      echo "$INITIAL_NODES" > /opt/web-data/nodes.json
      ok "nodes.json 已初始化（包含本地 Reality 与 Hysteria2 节点）"
    fi
  fi
fi

# ---------- 6. 开启 BBR 拥塞控制 ----------
say "6/10 开启系统 BBR 拥塞控制"
if modprobe tcp_bbr 2>/dev/null; then
  if [ "$DRY_RUN" = 0 ]; then
    echo "tcp_bbr" > /etc/modules-load.d/bbr.conf 2>/dev/null || true
    cat > /etc/sysctl.d/99-bbr.conf << 'BBR'
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
BBR
    sysctl -p /etc/sysctl.d/99-bbr.conf >/dev/null 2>&1 || true
  fi
  ok "BBR 拥塞控制已开启并持久化"
else
  warn "内核模块未提供 tcp_bbr，跳过 BBR 设置"
fi

# ---------- 7. 防火墙端口放行 ----------
say "7/10 本机防火墙放行端口 (80/tcp, 443/tcp, 443/udp, 8443/tcp)"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  run ufw allow 80/tcp >/dev/null 2>&1 || true
  run ufw allow 443/tcp >/dev/null 2>&1 || true
  run ufw allow 443/udp >/dev/null 2>&1 || true
  run ufw allow 8443/tcp >/dev/null 2>&1 || true
  ok "UFW 已放行 80/tcp, 443/tcp, 443/udp, 8443/tcp"
fi
if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
  run firewall-cmd --permanent --add-port=80/tcp --add-port=443/tcp --add-port=443/udp --add-port=8443/tcp >/dev/null 2>&1 || true
  run firewall-cmd --reload >/dev/null 2>&1 || true
  ok "firewalld 已放行 80/tcp, 443/tcp, 443/udp, 8443/tcp"
fi

# ---------- 8. 写入 settings.json 与 Caddyfile ----------
say "8/10 渲染 settings.json 与 Caddyfile"
TOKEN=""
PANEL_PASS=""

if [ -f /opt/web-data/settings.json ]; then
  TOKEN=$(python3 -c "import json; print(json.load(open('/opt/web-data/settings.json')).get('sub_token',''))" 2>/dev/null || true)
  warn "settings.json 已存在，沿用现有订阅 token: $TOKEN"
fi
if [ -z "$TOKEN" ]; then
  TOKEN=$(openssl rand -hex 5)
  if [ "$DRY_RUN" = 0 ]; then
    cat > /opt/web-data/settings.json << EOF
{
  "sub_token": "$TOKEN",
  "domain": "$DOMAIN",
  "sub_port": 8443,
  "sub_backend": "builtin"
}
EOF
    chmod 600 /opt/web-data/settings.json
  fi
  ok "settings.json 已生成（token: $TOKEN）"
fi

if [ -f /etc/caddy/Caddyfile ]; then
  warn "Caddyfile 已存在，保留不动（面板密码与证书配置未重置）"
  PANEL_PASS="(沿用原密码)"
else
  PANEL_PASS=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)
  if [ "$DRY_RUN" = 0 ]; then
    PASS_HASH=$(caddy hash-password --plaintext "$PANEL_PASS")
    TLS_DIRECTIVE=""
    if [ "$TLS_INTERNAL" = 1 ]; then
      TLS_DIRECTIVE="tls internal"
    fi

    cat > /etc/caddy/Caddyfile << CADDYEOF
(app) {
	redir /p / 308
	redir /p/* / 308

	# 订阅路由：交由 admin.py 统一处理（支持 Base64 / Clash YAML 智能分发与 Token 鉴权）
	handle /s/* {
		reverse_proxy 127.0.0.1:8099
	}

	@blocked path /sub*
	handle @blocked {
		respond 404
	}

	handle_path /api/* {
		basic_auth {
			admin $PASS_HASH
		}
		reverse_proxy 127.0.0.1:8099
	}

	@sensitive path /tc.json /nodes.json /retired-nodes-*.json
	handle @sensitive {
		respond 404
	}

	@pubjson path /status.json /servers.json /usage.json /quota.json
	handle @pubjson {
		basic_auth {
			admin $PASS_HASH
		}
		header Cache-Control "no-store"
		root * /opt/web-data
		file_server
	}

	handle {
		basic_auth {
			admin $PASS_HASH
		}
		header Cache-Control "no-store"
		root * /opt/web
		file_server
	}
}

:80 {
	redir https://${DOMAIN}:8443{uri} 308
}

https://${DOMAIN}:8443 {
	$TLS_DIRECTIVE
	import app
}
CADDYEOF
  fi
  ok "Caddyfile 已渲染生成"
fi

# ---------- 9. 启动 systemd 服务 ----------
say "9/10 安装并启动系统服务"
if [ -d "$SRC_DEPLOY/systemd" ]; then
  run cp "$SRC_DEPLOY"/systemd/*.service "$SRC_DEPLOY"/systemd/*.timer /etc/systemd/system/ 2>/dev/null || true
fi
run systemctl daemon-reload
run systemctl enable --now sing-box admin probe.timer usage-refresh.timer ipcheck.timer backup-remote.timer
run systemctl enable caddy
run systemctl restart caddy
ok "全部系统服务与定时器已启动"

# ---------- 10. 部署自检 ----------
say "10/10 部署自检"
SUB_URL="https://${DOMAIN}:8443/s/${TOKEN}"
if [ "$DRY_RUN" = 0 ]; then
  sleep 2
  for s in sing-box admin caddy; do
    systemctl is-active --quiet "$s" && ok "服务 $s 运行正常" || warn "服务 $s 未正常运行，请检查 journalctl -u $s"
  done

  # 探针自测
  if curl -s -k --connect-timeout 4 -o /dev/null "https://127.0.0.1:8443/s/${TOKEN}"; then
    ok "本地订阅接口响应正常 (HTTP 200)"
  else
    warn "本地订阅接口访问异常"
  fi
fi

cat <<EOF

─────────────────────────────────────────────────────────────
🎉 Ladder 主控与出口节点部署完成！请妥善保存以下信息：

  面板地址:   https://${DOMAIN}:8443/
  面板账号:   admin
  面板密码:   ${PANEL_PASS}
  订阅地址:   ${SUB_URL}

⚠️ 云厂商安全组放行提示：
  若面板打不开或客户端拉取超时，请前往云控制台（腾讯云/阿里云/AWS等）放行以下端口：
  - 80/tcp     (Caddy 申请正式证书与 HTTP 重定向)
  - 8443/tcp   (Web 管理面板与客户端订阅)
  - 443/tcp    (sing-box VLESS Reality 代理)
  - 443/udp    (sing-box Hysteria2 / QUIC 高速代理)

📲 客户端导入二维码（终端直扫 / Shadowrocket / Clash 支持）：
─────────────────────────────────────────────────────────────
EOF

if command -v qrencode >/dev/null 2>&1 && [ "$DRY_RUN" = 0 ]; then
  qrencode -t ansiutf8 "$SUB_URL" 2>/dev/null || true
fi
