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
CADDY_VERSION="2.10.2"
CADDY_SHA512_AMD64="747df7ee74de188485157a383633a1a963fd9233b71fbb4a69ddcbcc589ce4e2cc82dacf5dbbe136cb51d17e14c59daeb5d9bc92487610b0f3b93680b2646546"
CADDY_SHA512_ARM64="6ce061a690312ab38367df3c5d5f89a2e4a263e7300d300d87356211bb81e79b15933e6d6203e03fbf26f15cc0311f264805f336147dbdd24938d84b57a4421c"

DOMAIN=""
TLS_INTERNAL=0
DRY_RUN=0
UNINSTALL=0
PURGE=0
SETUP_JOB=""
SETUP_TOKEN=""
SETUP_HASH=""
SETUP_PUBLIC_IP=""
# Track whether this file belonged to the machine before apt could create a
# distribution-default Caddyfile during this installation.
CADDYFILE_PREEXISTING=0
[ ! -f /etc/caddy/Caddyfile ] || CADDYFILE_PREEXISTING=1

while [ $# -gt 0 ]; do
  case "$1" in
    --setup-stdin)
      # Fixed installer protocol: temporary SSH credentials never reach this script.
      read -r SETUP_JOB; read -r SETUP_TOKEN; read -r SETUP_HASH; read -r DOMAIN; read -r SETUP_PUBLIC_IP
      [[ "$SETUP_JOB" =~ ^[0-9a-f]{32}$ ]] || { echo "invalid setup job" >&2; exit 2; }
      [[ "$SETUP_TOKEN" =~ ^[0-9a-f]{64}$ ]] || { echo "invalid setup token" >&2; exit 2; }
      [[ "$SETUP_HASH" == '$2'* ]] || { echo "invalid password hash" >&2; exit 2; }
      shift ;;
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

# Only fixed official release URLs and pinned hashes are passed here. Never
# execute the response until it passes the independent checksum in this script.
fetch_verified() {
  local url="$1" algorithm="$2" expected="$3" destination="$4" prefix actual
  for prefix in 'https://ghproxy.net/' 'https://ghfast.top/' ''; do
    if curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 8 --max-time 180 -o "$destination" "${prefix}${url}"; then
      actual=$("${algorithm}sum" "$destination" | awk '{print $1}')
      [ "$actual" != "$expected" ] || return 0
      warn "下载文件校验未通过，尝试其他来源"
    fi
    rm -f "$destination"
  done
  return 1
}

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

# FIRST INSTALL CONFLICT CHECK BEGIN
installation_conflict() {
  local base="${1:-/}" path service
  for path in /etc/caddy/Caddyfile /opt/sing-box/config.json /opt/web/admin.py \
      /opt/web-data/nodes.json /opt/web-data/settings.json \
      /etc/systemd/system/caddy.service /lib/systemd/system/caddy.service /usr/lib/systemd/system/caddy.service \
      /etc/systemd/system/sing-box.service /lib/systemd/system/sing-box.service \
      /usr/lib/systemd/system/sing-box.service /etc/systemd/system/admin.service; do
    if [ -e "${base%/}${path}" ]; then
      printf '已有配置或服务文件：%s\n' "$path"
      return 0
    fi
  done
  for service in caddy sing-box admin; do
    if systemctl is-active --quiet "$service" 2>/dev/null; then
      printf '已有正在运行的服务：%s\n' "$service"
      return 0
    fi
  done
  return 1
}
# FIRST INSTALL CONFLICT CHECK END

# ---------- 0. 前置检查 ----------
say "0/10 预检运行环境"
[ "$(id -u)" = "0" ] || die "必须使用 root 权限运行: sudo $0"
[ -d /run/systemd/system ] || die "系统缺少 systemd 支持"
command -v apt-get >/dev/null 2>&1 || die "目前仅支持 Debian / Ubuntu 系统 (apt-get)"

# A direct invocation is first install, not an update or adoption mechanism.
# SETUP_JOB is a separately validated resumable task managed by its supervisor.
if [ "$DRY_RUN" = 0 ] && [ -z "$SETUP_JOB" ]; then
  if conflict=$(installation_conflict); then
    die "$conflict；为保护现有业务，已停止安装，请人工检查后选择空白服务器"
  fi
fi

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
    warn "常用连通性探测未通过，将继续检查安装资源的实际可达性。"
  else
    ok "海外直连网络正常"
  fi
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
say "1/10 安装系统依赖 (python3 / curl / openssl / qrencode / sshpass / caddy)"
APT_PACKAGES=(curl openssl ca-certificates python3 python3-pip gnupg debian-keyring debian-archive-keyring apt-transport-https qrencode sshpass openssh-client)
APT_NET=(-o 'Acquire::Retries=0' -o 'Acquire::http::Timeout=10' -o 'Acquire::https::Timeout=10')
if ! run apt-get "${APT_NET[@]}" update -qq || ! run apt-get "${APT_NET[@]}" install -y -qq "${APT_PACKAGES[@]}"; then
  # This temporary source is used only by this invocation. System source files and
  # apt signature verification are left intact.
  [ "$DRY_RUN" = 0 ] || die "系统依赖检查失败"
  . /etc/os-release
  [[ "${VERSION_CODENAME:-}" =~ ^[a-z0-9-]+$ ]] || { warn "无法识别系统代号"; exit 81; }
  MIRROR_DIR=/run/ownline-installer/apt
  install -d -m 700 "$MIRROR_DIR"
  MIRROR_LIST="$MIRROR_DIR/sources.list"
  case "$ID" in
    debian)
      MIRROR_KEYRING=/usr/share/keyrings/debian-archive-keyring.gpg
      [ -r "$MIRROR_KEYRING" ] || { warn "缺少 Debian 官方软件源密钥"; exit 81; }
      printf 'deb [signed-by=%s] https://mirrors.tuna.tsinghua.edu.cn/debian/ %s main contrib non-free\ndeb [signed-by=%s] https://mirrors.tuna.tsinghua.edu.cn/debian/ %s-updates main contrib non-free\ndeb [signed-by=%s] https://mirrors.tuna.tsinghua.edu.cn/debian-security/ %s-security main contrib non-free\n' "$MIRROR_KEYRING" "$VERSION_CODENAME" "$MIRROR_KEYRING" "$VERSION_CODENAME" "$MIRROR_KEYRING" "$VERSION_CODENAME" > "$MIRROR_LIST" ;;
    ubuntu)
      if [ "$SB_ARCH" = arm64 ]; then UBUNTU_REPO=ubuntu-ports; else UBUNTU_REPO=ubuntu; fi
      MIRROR_KEYRING=/usr/share/keyrings/ubuntu-archive-keyring.gpg
      [ -r "$MIRROR_KEYRING" ] || { warn "缺少 Ubuntu 官方软件源密钥"; exit 81; }
      printf 'deb [signed-by=%s] https://mirrors.tuna.tsinghua.edu.cn/%s/ %s main restricted universe multiverse\ndeb [signed-by=%s] https://mirrors.tuna.tsinghua.edu.cn/%s/ %s-updates main restricted universe multiverse\ndeb [signed-by=%s] https://mirrors.tuna.tsinghua.edu.cn/%s/ %s-security main restricted universe multiverse\n' "$MIRROR_KEYRING" "$UBUNTU_REPO" "$VERSION_CODENAME" "$MIRROR_KEYRING" "$UBUNTU_REPO" "$VERSION_CODENAME" "$MIRROR_KEYRING" "$UBUNTU_REPO" "$VERSION_CODENAME" > "$MIRROR_LIST" ;;
    *) warn "不支持此系统的镜像源"; exit 81 ;;
  esac
  APT_MIRROR=("${APT_NET[@]}" -o "Dir::Etc::sourcelist=$MIRROR_LIST" -o 'Dir::Etc::sourceparts=-' -o 'APT::Get::List-Cleanup=0')
  if ! apt-get "${APT_MIRROR[@]}" update -qq || ! apt-get "${APT_MIRROR[@]}" install -y -qq "${APT_PACKAGES[@]}"; then
    warn "系统依赖来源不可用，请检查网络后复查原任务"; exit 81
  fi
fi

if ! command -v caddy >/dev/null 2>&1; then
  ok "从官方源安装 Caddy"
  if [ "$DRY_RUN" = 0 ]; then
    CADDY_APT_DIR=/run/ownline-installer/apt-caddy
    install -d -m 700 "$CADDY_APT_DIR"
    CADDY_APT=("${APT_NET[@]}" -o "Dir::Etc::sourcelist=$CADDY_APT_DIR/source.list" -o 'Dir::Etc::sourceparts=-' -o 'APT::Get::List-Cleanup=0')
    if curl -1sLf --connect-timeout 8 --max-time 30 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' -o "$CADDY_APT_DIR/key.asc" &&
       gpg --batch --yes --dearmor -o "$CADDY_APT_DIR/key.gpg" "$CADDY_APT_DIR/key.asc" &&
       curl -1sLf --connect-timeout 8 --max-time 30 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' -o "$CADDY_APT_DIR/source.original" &&
       sed "s|/usr/share/keyrings/caddy-stable-archive-keyring.gpg|$CADDY_APT_DIR/key.gpg|g" "$CADDY_APT_DIR/source.original" > "$CADDY_APT_DIR/source.list" &&
       apt-get "${CADDY_APT[@]}" update -qq &&
       CADDY_APT_VERSION=$(apt-cache "${CADDY_APT[@]}" madison caddy | awk -v version="$CADDY_VERSION" '$3 == version || index($3,version "-") == 1 {print $3;exit}') &&
       [ -n "$CADDY_APT_VERSION" ] &&
       apt-get "${CADDY_APT[@]}" install -y -qq "caddy=$CADDY_APT_VERSION"; then
      ok "Caddy 官方软件源安装完成"
    else
      CADDY_PACKAGE="$REPO/packages/caddy_${CADDY_VERSION}_linux_${SB_ARCH}.tar.gz"
      if [ "$SB_ARCH" = arm64 ]; then CADDY_EXPECTED="$CADDY_SHA512_ARM64"; else CADDY_EXPECTED="$CADDY_SHA512_AMD64"; fi
      if [ ! -f "$CADDY_PACKAGE" ] || [ "$(sha512sum "$CADDY_PACKAGE" | awk '{print $1}')" != "$CADDY_EXPECTED" ]; then
        CADDY_PACKAGE="/run/ownline-installer/caddy-${SB_ARCH}.tar.gz"
        install -d -m 700 /run/ownline-installer
        CADDY_URL="https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${SB_ARCH}.tar.gz"
        fetch_verified "$CADDY_URL" sha512 "$CADDY_EXPECTED" "$CADDY_PACKAGE" || { warn "无法获取已校验的 Caddy，请检查网络后复查原任务"; exit 82; }
      fi
      if [ -e /etc/systemd/system/caddy.service ] || [ -e /lib/systemd/system/caddy.service ]; then
        die "检测到已有 Caddy 服务，未覆盖；请先核对"
      fi
      install -d -m 755 /usr/local/bin /etc/caddy /var/lib/caddy
      tar xOf "$CADDY_PACKAGE" caddy > /usr/local/bin/caddy
      chmod 755 /usr/local/bin/caddy
      getent group caddy >/dev/null || groupadd --system caddy
      getent passwd caddy >/dev/null || useradd --system --gid caddy --home-dir /var/lib/caddy --shell /usr/sbin/nologin caddy
      chown caddy:caddy /var/lib/caddy
      cat > /etc/systemd/system/caddy.service <<'CADDYUNIT'
[Unit]
Description=Caddy HTTPS server
After=network-online.target
Wants=network-online.target
[Service]
Type=notify
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile --force
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
CADDYUNIT
      ok "已安装经校验的 Caddy 官方发行包"
    fi
  fi
else
  ok "Caddy 已就位: $(caddy version 2>/dev/null | head -1)"
fi

# basic_auth syntax requires Caddy >= 2.8; fail clearly instead of delivering a broken dashboard.
if [ "$DRY_RUN" = 0 ]; then
  CADDY_VERSION=$(caddy version | awk '{print $1}' | sed 's/^v//')
  [ "$(printf '%s\n' 2.8.0 "$CADDY_VERSION" | sort -V | head -1)" = "2.8.0" ] || die "需要 Caddy 2.8+；请先更新已有 Caddy，再检查原任务"
fi

# ---------- 2. sing-box 安装与校验 ----------
say "2/10 安装并校验 sing-box $SINGBOX_VERSION"
run mkdir -p /opt/sing-box /opt/sing-box/pkg
if [ "$DRY_RUN" = 0 ]; then
  cat > /opt/sing-box/pkg/SHA256SUMS <<SHAEOF
${SHA256_AMD64}  sing-box-${SINGBOX_VERSION}-linux-amd64.tar.gz
${SHA256_ARM64}  sing-box-${SINGBOX_VERSION}-linux-arm64.tar.gz
SHAEOF
  chmod 644 /opt/sing-box/pkg/SHA256SUMS
fi
if [ -x /opt/sing-box/sing-box ]; then
  ok "sing-box 已存在: $(/opt/sing-box/sing-box version 2>/dev/null | head -1)"
else
  URL="https://github.com/SagerNet/sing-box/releases/download/v$SINGBOX_VERSION/sing-box-$SINGBOX_VERSION-linux-$SB_ARCH.tar.gz"
  CACHED_PKG="/opt/sing-box/pkg/sing-box-$SINGBOX_VERSION-linux-$SB_ARCH.tar.gz"
  if [ "$DRY_RUN" = 0 ]; then
    if [ -f "$REPO/packages/sing-box-$SINGBOX_VERSION-linux-$SB_ARCH.tar.gz" ]; then
      cp "$REPO/packages/sing-box-$SINGBOX_VERSION-linux-$SB_ARCH.tar.gz" "$CACHED_PKG"
    elif [ ! -f "$CACHED_PKG" ] || [ "$(sha256sum "$CACHED_PKG" | awk '{print $1}')" != "$EXPECTED_SHA" ]; then
      fetch_verified "$URL" sha256 "$EXPECTED_SHA" "$CACHED_PKG" || { warn "无法获取 sing-box，请检查网络后复查原任务"; exit 83; }
    fi
    ACTUAL_SHA=$(sha256sum "$CACHED_PKG" | awk '{print $1}')
    if [ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]; then
      rm -f "$CACHED_PKG"
      warn "sing-box 校验和不匹配，请复查原任务"
      exit 83
    fi
    chmod 644 "$CACHED_PKG"
    tar xzf "$CACHED_PKG" -C /opt/sing-box --strip-components=1
  fi
  ok "sing-box $SINGBOX_VERSION 校验通过并安装成功"
fi

# 生成主控 SSH 管理密钥对（供扩容节点授权、远端配置同步与连通核验使用）
if [ "$DRY_RUN" = 0 ]; then
  install -d -m 700 /root/.ssh
  if [ ! -f /root/.ssh/node_ctl ] || [ ! -f /root/.ssh/node_ctl.pub ]; then
    rm -f /root/.ssh/node_ctl /root/.ssh/node_ctl.pub
    ssh-keygen -t ed25519 -N "" -C "ownline-node-ctl" -f /root/.ssh/node_ctl >/dev/null
  fi
  chmod 600 /root/.ssh/node_ctl
  chmod 644 /root/.ssh/node_ctl.pub
  ok "主控节点管理密钥已就绪 (/root/.ssh/node_ctl)"
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
  if [ -f "$SRC_WEB/backup-crypto.js" ]; then run cp "$SRC_WEB/backup-crypto.js" /opt/web/; fi
  if [ -f "$SRC_WEB/change-password.html" ]; then run cp "$SRC_WEB/change-password.html" /opt/web/; fi
  if [ -d "$SRC_WEB/assets" ]; then run cp -r "$SRC_WEB/assets" /opt/web/; fi
  run chmod 755 /opt/web/*.sh /opt/web/*.py 2>/dev/null || true
fi

# SSH checking runs outside the web root with separately locked dependencies.
# If its optional dependency download fails, the main service remains usable
# and the page keeps the connection control disabled.
if [ "$DRY_RUN" = 0 ] && [ -f "$SRC_SERVER/nodekit/sshcheck/node_check.py" ] && [ -f "$REPO/requirements.lock" ] && [ -f "$SRC_DEPLOY/install-python-deps.sh" ]; then
  NODECHECK_DIR=/opt/ownline-nodecheck
  install -d -m 755 "$NODECHECK_DIR/sshcheck"
  install -m 644 "$SRC_SERVER/nodekit/sshcheck/__init__.py" "$SRC_SERVER/nodekit/sshcheck/problem.py" "$SRC_SERVER/nodekit/sshcheck/transport.py" "$SRC_SERVER/nodekit/sshcheck/node_check.py" "$NODECHECK_DIR/sshcheck/"
  # Remove the legacy Flask-installer copy left by older releases.
  rm -rf "$NODECHECK_DIR/installer"
  if [ ! -e "$NODECHECK_DIR/deps" ]; then
    NODECHECK_STAGE=$(mktemp -d "$NODECHECK_DIR/.deps-stage.XXXXXXXX")
    if python3 - "$REPO/requirements.lock" "$NODECHECK_STAGE/requirements.lock" <<'PY'
import re, sys
from pathlib import Path
want = {'bcrypt', 'cffi', 'cryptography', 'invoke', 'paramiko', 'pycparser', 'pynacl', 'typing-extensions'}
lines, selected, found, take = Path(sys.argv[1]).read_text().splitlines(keepends=True), [], set(), False
for line in lines:
    match = re.match(r'^([A-Za-z0-9_-]+)==', line)
    if match:
        name = match.group(1).lower()
        take = name in want
        if take: found.add(name)
    if take: selected.append(line)
if found != want: raise SystemExit('missing locked SSH dependency')
Path(sys.argv[2]).write_text(''.join(selected))
PY
    then
      if "$SRC_DEPLOY/install-python-deps.sh" /usr/bin/python3 "$NODECHECK_STAGE" "$NODECHECK_STAGE/requirements.lock" && PYTHONPATH="$NODECHECK_STAGE" PYTHONNOUSERSITE=1 /usr/bin/python3 -c 'import paramiko'; then
        mv "$NODECHECK_STAGE" "$NODECHECK_DIR/deps"
      else
        warn "SSH 检查依赖暂不可用，可稍后重新安装；主服务不受影响。"
      fi
    else
      warn "SSH 检查依赖清单不完整；主服务不受影响。"
    fi
  fi
fi
ok "代码与脚本部署完成"

# ---------- 4. 确定公网 IP 与域名 ----------
say "4/10 确定公网 IP 与服务域名"
PUB_IP=""
if [ "$DRY_RUN" = 0 ]; then
  PUB_IP="${SETUP_PUBLIC_IP:-}"
  [ -n "$PUB_IP" ] || PUB_IP=$(curl -fsSL --connect-timeout 4 https://api.ipify.org 2>/dev/null || curl -fsSL --connect-timeout 4 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
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

# The hostname enters the Caddyfile and curl config. Do not accept Caddyfile
# syntax, URL components, whitespace or quotes as a hostname.
if [ ${#DOMAIN} -gt 253 ] || [[ ! "$DOMAIN" =~ ^[A-Za-z0-9]+([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]+([A-Za-z0-9-]*[A-Za-z0-9])?)*$ ]]; then
  die "管理网页域名无效，请只填写主机名"
fi
IFS='.' read -r -a _domain_labels <<< "$DOMAIN"
for _label in "${_domain_labels[@]}"; do
  [ ${#_label} -le 63 ] || die "管理网页域名无效，请只填写主机名"
done

# ---------- 5. 生成本机双协议出口节点 (Reality + Hysteria2) ----------
say "5/10 生成并校验本机出口节点配置"
SINGBOX_BIN="/opt/sing-box/sing-box"

if [ "$DRY_RUN" = 0 ]; then
  python3 - "$PUB_IP" <<'PYSEED'
import json, os, secrets, subprocess, sys
from pathlib import Path
sys.path.insert(0, "/opt/web")
from nodekit import templates
binary="/opt/sing-box/sing-box"
config=Path("/opt/sing-box/config.json");nodes=Path("/opt/web-data/nodes.json");seed=Path("/opt/web-data/.setup-seed.json")
def atomic(path,value):
    temporary=path.with_suffix(path.suffix+".tmp")
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,"w") as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)
if config.exists() and nodes.exists():
    print("已有配置与节点底账，保留不动")
    raise SystemExit
if seed.exists():
    saved=json.loads(seed.read_text());cfg=saved["config"];records=saved["nodes"]
    if config.exists() and json.loads(config.read_text())!=cfg:raise SystemExit("已有配置与恢复快照不一致")
elif config.exists() or nodes.exists():
    raise SystemExit("配置与底账不完整，未自动重建")
else:
    uid=subprocess.check_output([binary,"generate","uuid"],text=True).strip()
    lines=subprocess.check_output([binary,"generate","reality-keypair"],text=True).splitlines()
    keys={line.split(":",1)[0]:line.split(":",1)[1].strip() for line in lines if ":" in line}
    sid=secrets.token_hex(4);password=secrets.token_hex(16);obfs=secrets.token_hex(16)
    subprocess.run(["openssl","req","-x509","-nodes","-newkey","rsa:2048","-keyout","/opt/sing-box/hy2.key","-out","/opt/sing-box/hy2.crt","-days","3650","-subj","/CN=www.bing.com"],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    os.chmod("/opt/sing-box/hy2.key",0o600)
    cfg=templates.exit_config(443,uid,"www.apple.com",keys["PrivateKey"],sid,hy2={"port":443,"password":password,"obfs_password":obfs,"sni":"www.bing.com","cert_path":"/opt/sing-box/hy2.crt","key_path":"/opt/sing-box/hy2.key"})
    if templates.validate(cfg):raise SystemExit("节点配置验证失败")
    records=[{"name":"主控-出口","host":sys.argv[1],"port":443,"uuid":uid,"sni":"www.apple.com","pbk":keys["PublicKey"],"sid":sid,"role":"exit","source":"builtin","local":True,"quota_control_managed":True,"health":"unknown"},
             {"name":"主控-出口-HY2","type":"hysteria2","host":sys.argv[1],"port":443,"password":password,"sni":"www.bing.com","obfs_password":obfs,"role":"exit","source":"builtin","local":True,"quota_control_managed":True,"health":"unknown"}]
    atomic(seed,{"config":cfg,"nodes":records})
if not config.exists():
    staged=config.with_suffix(".staged.json");atomic(staged,cfg)
    subprocess.run([binary,"check","-c",str(staged)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    os.replace(staged,config)
if not nodes.exists():atomic(nodes,records)
seed.unlink(missing_ok=True)
print("节点配置与底账已提交")
PYSEED
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
  warn "settings.json 已存在，保留现有订阅配置"
fi
if [ -z "$TOKEN" ]; then
  TOKEN="${SETUP_TOKEN:-$(openssl rand -hex 32)}"
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
  ok "settings.json 已生成"
fi

if [ -f /etc/caddy/Caddyfile ] && { { [ -z "$SETUP_JOB" ] && [ "$CADDYFILE_PREEXISTING" = 1 ]; } || { [ -n "$SETUP_JOB" ] && grep -qF "# ownline-setup-job:$SETUP_JOB" /etc/caddy/Caddyfile; }; }; then
  warn "Caddyfile 已存在，保留不动（面板密码与证书配置未重置）"
  PANEL_PASS="(沿用原密码)"
else
  PANEL_PASS=""
  [ -n "$SETUP_JOB" ] || PANEL_PASS=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)
  if [ "$DRY_RUN" = 0 ]; then
    if [ -n "$SETUP_JOB" ]; then PASS_HASH="$SETUP_HASH"; else PASS_HASH=$(printf '%s\n' "$PANEL_PASS" | caddy hash-password); fi
    TLS_DIRECTIVE=""
    if [ "$TLS_INTERNAL" = 1 ]; then
      TLS_DIRECTIVE="tls internal"
    fi

    # Establish the durable gate before publishing its Caddyfile; interruption
    # between the two must fail closed, never skip the first-login requirement.
    # The enclosing branch runs only for a newly generated configuration.
    python3 - <<'PY'
import os
directory = '/opt/web-data'
path = directory + '/.initial-password-required'
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
try:
    os.fchmod(fd, 0o600)
    os.fsync(fd)
finally:
    os.close(fd)
dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(dirfd)
finally:
    os.close(dirfd)
PY
    CADDY_STAGED="$(mktemp /etc/caddy/.ownline-Caddyfile-XXXXXX)"
    cat > "$CADDY_STAGED" << CADDYEOF
# ownline-setup-job:$SETUP_JOB
# ownline-managed-password-v1
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

	handle /change-password {
		basic_auth {
			admin $PASS_HASH
		}
		root * /opt/web
		rewrite * /change-password.html
		file_server
	}

	handle /api/password/* {
		basic_auth {
			admin $PASS_HASH
		}
		reverse_proxy 127.0.0.1:8099
	}

	handle_path /api/* {
		basic_auth {
			admin $PASS_HASH
		}
		forward_auth 127.0.0.1:8099 {
			uri /password-gate
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
		forward_auth 127.0.0.1:8099 {
			uri /password-gate
		}
		header Cache-Control "no-store"
		root * /opt/web-data
		file_server
	}

	handle {
		basic_auth {
			admin $PASS_HASH
		}
		forward_auth 127.0.0.1:8099 {
			uri /password-gate
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
    if ! caddy validate --config "$CADDY_STAGED" --adapter caddyfile >/dev/null 2>&1; then
      rm -f "$CADDY_STAGED"
      die "管理网页配置未通过检查，未发布；请检查后继续原安装"
    fi
    chmod 644 "$CADDY_STAGED"
    python3 - "$CADDY_STAGED" <<'PY'
import os, sys
fd = os.open(sys.argv[1], os.O_RDONLY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
    mv -f "$CADDY_STAGED" /etc/caddy/Caddyfile
    python3 - <<'PY'
import os
fd = os.open('/etc/caddy', os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(fd)
finally:
    os.close(fd)
PY
  fi
  ok "Caddyfile 已渲染生成"
fi

# ---------- 9. 启动 systemd 服务 ----------
say "9/10 安装并启动系统服务"
if [ -d "$SRC_DEPLOY/systemd" ]; then
  run cp "$SRC_DEPLOY"/systemd/*.service "$SRC_DEPLOY"/systemd/*.timer /etc/systemd/system/ 2>/dev/null || true
fi
run systemctl daemon-reload
# A long download never holds this short lifecycle lock. Quota stop can acquire it independently.
run systemctl enable sing-box
if [ "$DRY_RUN" = 0 ]; then
  flock -x -w 5 /run/ownline-service.lock sh -c 'test ! -e /var/lib/ownline/quota-paused && systemctl start sing-box' || die "代理处于保护状态或启动失败，请复查"
fi
run systemctl enable --now admin probe.timer usage-refresh.timer ipcheck.timer
run systemctl enable caddy
run systemctl restart caddy
ok "全部系统服务与定时器已启动"

# DELIVERY VERIFICATION FUNCTIONS BEGIN
# Token is passed to curl on stdin, not in its command line or in log output.
delivery_http_status() {
  local url="$1" resolve="${2:-}" code
  if [ -n "$resolve" ]; then
    code=$(printf 'url = "%s"\n' "$url" | curl --disable --config - --silent --show-error --noproxy '*' --connect-timeout 4 --max-time 10 --resolve "$resolve" --output /dev/null --write-out '%{http_code}' 2>/dev/null) || return 1
  else
    code=$(printf 'url = "%s"\n' "$url" | curl --disable --config - --silent --show-error --noproxy '*' --connect-timeout 4 --max-time 10 --output /dev/null --write-out '%{http_code}' 2>/dev/null) || return 1
  fi
  [[ "$code" =~ ^[0-9]{3}$ ]] || return 1
  printf '%s' "$code"
}

# Check DNS as well as the named certificate; pin the connection to the target
# IP so the subscription credential is never sent to an unrelated DNS target.
delivery_dns_matches() {
  local domain="$1" ip="$2"
  getent ahostsv4 "$domain" 2>/dev/null | awk '{print $1}' | grep -Fxq -- "$ip"
}
# DELIVERY VERIFICATION FUNCTIONS END

# ---------- 10. 部署自检 ----------
say "10/10 部署自检"
DELIVERY_READY=0
if [ "$DRY_RUN" = 0 ]; then
  sleep 2
  services_ok=1
  for s in sing-box admin caddy; do
    if systemctl is-active --quiet "$s"; then
      ok "服务 $s 正在运行"
    else
      services_ok=0
      warn "服务 $s 未正常运行，请检查 journalctl -u $s"
    fi
  done

  local_ok=0
  if [[ "$TOKEN" =~ ^[0-9a-fA-F]{8,64}$ ]] && [ "$(delivery_http_status "http://127.0.0.1:8099/s/${TOKEN}" || true)" = 200 ]; then
    local_ok=1
    ok "本地订阅接口响应正常 (HTTP 200)"
  else
    warn "本地订阅接口未验证，请检查 admin 服务和订阅配置"
  fi

  panel_ok=0
  if delivery_dns_matches "$DOMAIN" "$PUB_IP" && \
      [ "$(delivery_http_status "https://${DOMAIN}:8443/" "${DOMAIN}:8443:${PUB_IP}" || true)" = 401 ]; then
    panel_ok=1
    ok "本机已验证管理地址的 TLS 证书和登录响应（HTTP 401）"
    warn "仍需从其他设备确认公网可访问"
  else
    warn "管理地址尚未验证：请检查域名解析、公网端口和可信 TLS 证书"
  fi
  if [ "$services_ok" = 1 ] && [ "$local_ok" = 1 ] && [ "$panel_ok" = 1 ]; then
    DELIVERY_READY=1
  fi
fi

if [ -z "$SETUP_JOB" ] && [ "$DRY_RUN" = 1 ]; then
  warn "演练模式未安装服务，也未生成可登录的管理地址和密码"
elif [ -z "$SETUP_JOB" ]; then
if [ "$DELIVERY_READY" = 1 ]; then
  DELIVERY_TITLE="安装脚本执行完毕；请从其他设备确认管理页面可访问。"
  DELIVERY_ADDRESS="管理地址"
else
  DELIVERY_TITLE="安装脚本执行完毕，但管理入口尚未验证，请先处理上方提示。"
  DELIVERY_ADDRESS="候选管理地址"
fi
cat <<EOF

─────────────────────────────────────────────────────────────
${DELIVERY_TITLE}

  ${DELIVERY_ADDRESS}: https://${DOMAIN}:8443/
  面板账号:   admin
  面板密码:   ${PANEL_PASS}

请妥善保存管理账号密码。验证管理网页后，从网页获取订阅链接。

⚠️ 云厂商安全组放行提示：
  若面板打不开或客户端拉取超时，请前往云控制台（腾讯云/阿里云/AWS等）放行以下端口：
  - 80/tcp     (Caddy 申请正式证书与 HTTP 重定向)
  - 8443/tcp   (Web 管理面板与客户端订阅)
  - 443/tcp    (sing-box VLESS Reality 代理)
  - 443/udp    (sing-box Hysteria2 / QUIC 高速代理)

─────────────────────────────────────────────────────────────
EOF

fi
