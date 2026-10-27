#!/usr/bin/env bash
# 一键部署：把本仓库装成一台能用的主控（面板 + 订阅 + 探活）
#
# 用法：
#   sudo ./deploy/install.sh v.example.com              # 真装
#   sudo ./deploy/install.sh v.example.com --dry-run    # 只打印要做什么
#
# 前提：
#   - Ubuntu 22.04+ / Debian 12+，root 权限，能访问外网
#   - 一个域名，已按 docs/DEPLOY.md 第 1 步接到 Cloudflare（不开 Cloudflare 也能跑，只是暴露源站 IP）
#
# 这个脚本做四件事：装依赖 → 放代码 → 生成配置 → 起服务。
# 它不做：加节点（那是面板的事）、配 Cloudflare（那是控制台的事）。
set -euo pipefail

SINGBOX_VERSION="${SINGBOX_VERSION:-1.14.4}"
DOMAIN="${1:-}"
DRY_RUN=0
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
run()  { if [ "$DRY_RUN" = 1 ]; then echo "  [dry-run] $*"; else "$@"; fi; }

[ -n "$DOMAIN" ] || die "用法: sudo $0 <你的域名> [--dry-run]"

# ---------- 0. 前置检查 ----------
say "0/7 前置检查"
[ "$(id -u)" = "0" ] || die "要用 root 跑：sudo $0 $DOMAIN"
[ -d /run/systemd/system ] || die "没有 systemd，这个脚本只支持 systemd 发行版"
command -v apt-get >/dev/null || die "只支持 Debian / Ubuntu（apt-get）"
case "$(uname -m)" in
  x86_64|aarch64) ok "架构 $(uname -m)" ;;
  *) die "不支持的架构：$(uname -m)" ;;
esac
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$REPO/server/admin.py" ] || die "找不到 $REPO/server/admin.py，请在仓库根目录跑"
ok "仓库路径 $REPO"
[ "$DRY_RUN" = 1 ] && warn "dry-run 模式：只打印，不执行"

# ---------- 1. 依赖 ----------
say "1/7 装系统依赖（caddy / python3 / curl / openssl）"
run apt-get update -qq
run apt-get install -y -qq curl openssl ca-certificates python3 gnupg debian-keyring debian-archive-keyring apt-transport-https
if ! command -v caddy >/dev/null; then
  ok "从官方源装 Caddy"
  if [ "$DRY_RUN" = 0 ]; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy
  fi
else
  ok "Caddy 已装：$(caddy version 2>/dev/null | head -1)"
fi

# ---------- 2. sing-box ----------
say "2/7 安装 sing-box $SINGBOX_VERSION"
if [ -x /opt/sing-box/sing-box ]; then
  ok "已存在：$(/opt/sing-box/sing-box version 2>/dev/null | head -1)"
  warn "跳过下载。要升级就删掉 /opt/sing-box/sing-box 重跑"
else
  case "$(uname -m)" in
    x86_64)  SB_ARCH=amd64 ;;
    aarch64) SB_ARCH=arm64 ;;
  esac
  URL="https://github.com/SagerNet/sing-box/releases/download/v$SINGBOX_VERSION/sing-box-$SINGBOX_VERSION-linux-$SB_ARCH.tar.gz"
  run mkdir -p /opt/sing-box
  if [ "$DRY_RUN" = 0 ]; then
    curl -fsSL -o /tmp/sing-box.tgz "$URL" || die "下载失败：$URL\n  国内机器可能拉不动 GitHub —— 手动下载后放到 /opt/sing-box/sing-box 再重跑"
    tar xzf /tmp/sing-box.tgz -C /opt/sing-box --strip-components=1
    rm -f /tmp/sing-box.tgz
  fi
  ok "sing-box 就位"
fi

# ---------- 3. subconverter-ng ----------
say "3/7 检查 subconverter-ng（订阅转换）"
if [ -x /opt/subconv/subconverter-ng ]; then
  ok "已存在"
else
  warn "没找到 /opt/subconv/subconverter-ng"
  warn "请按 docs/DEPLOY.md 第 2 步手动下载，然后重跑本脚本"
  warn "它监听 127.0.0.1:25500，少了它订阅接口会 502"
  [ "$DRY_RUN" = 1 ] || die "先装 subconverter-ng 再来"
fi

# ---------- 4. 放代码 ----------
say "4/7 部署代码到 /opt/web（数据放 /opt/web-data）"
run mkdir -p /opt/web /opt/web-data
run chmod 700 /opt/web-data
run cp -r "$REPO/server/providers" /opt/web/
run cp -r "$REPO/server/nodekit" /opt/web/
run cp "$REPO"/server/*.py /opt/web/
run cp "$REPO"/server/*.sh /opt/web/
run cp "$REPO/web/index.html" /opt/web/
run chmod 755 /opt/web/*.sh
ok "代码就位"

# ---------- 5. 生成配置 ----------
say "5/7 生成配置"
if [ -f /opt/web-data/nodes.json ]; then
  warn "nodes.json 已存在，保留不动"
else
  echo '[]' > /tmp/nodes.json
  run install -m 644 /tmp/nodes.json /opt/web-data/nodes.json
  ok "空节点表已建"
fi

TOKEN="$(openssl rand -hex 6)"
PANEL_PASS="$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-14)"
if [ "$DRY_RUN" = 1 ]; then
  PASS_HASH='<dry-run>'
else
  PASS_HASH="$(caddy hash-password --plaintext "$PANEL_PASS")"
fi

if [ -f /etc/caddy/Caddyfile ]; then
  # 已经装过：保留原样。重跑一次就换掉 token 和面板密码，会让所有设备掉线——
  # 这个坑在 2026-10-27 真机演练时踩到了。要改域名/密码请手动编辑这个文件。
  warn "Caddyfile 已存在，保留不动（token 和密码不会被重置）"
  TOKEN=$(grep -oE '/s/[a-f0-9]{6,}' /etc/caddy/Caddyfile | head -1 | cut -d/ -f2)
  PANEL_PASS="(沿用原密码，未重置)"
else
  if [ "$DRY_RUN" = 0 ]; then
    sed -e "s|<BCRYPT_HASH_OF_YOUR_PASSWORD>|$PASS_HASH|g" \
        -e "s|v.example.com|$DOMAIN|g" \
        -e "s|CHANGEME0000|$TOKEN|g" \
        -e "s|<URLENCODED_VLESS_LIST>|x|g" \
        "$REPO/deploy/Caddyfile.example" > /etc/caddy/Caddyfile
  fi
  ok "Caddyfile 已生成（域名 $DOMAIN，订阅 token $TOKEN）"
fi
warn "订阅源现在是占位值，加完第一个节点后由面板自动重渲染"

# ---------- 6. systemd ----------
say "6/7 安装并启动服务"
run cp "$REPO"/deploy/systemd/*.service "$REPO"/deploy/systemd/*.timer /etc/systemd/system/
run systemctl daemon-reload
run systemctl enable --now admin
run systemctl enable --now probe.timer
run systemctl enable --now usage-refresh.timer
run systemctl enable --now ipcheck.timer
if [ -x /opt/subconv/subconverter-ng ]; then
  run systemctl enable --now subconverter || warn "subconverter 没起来，订阅会 502"
fi
# Caddy 由 apt 装完会自动启动，enable --now 对已在跑的进程是空操作，
# 必须显式 restart 才会加载我们刚写的 Caddyfile。这一条在 2026-10-27 真机演练时踩到。
run systemctl enable caddy
run systemctl restart caddy
ok "服务已启动"

# ---------- 7. 自检 ----------
say "7/7 自检"
if [ "$DRY_RUN" = 0 ]; then
  sleep 2
  for s in admin caddy; do
    systemctl is-active --quiet "$s" && ok "$s 在跑" || warn "$s 没起来，看 journalctl -u $s"
  done
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1/s/$TOKEN" || true)
  [ "$code" = "404" ] && ok "订阅路径已生效（空节点表返回 404 属正常）" || warn "订阅返回 $code"
fi

cat <<EOF

────────────────────────────────────────
装完了。三件事要记下来（密码只显示这一次）：

  面板地址   https://$DOMAIN/
  面板账号   admin
  面板密码   $PANEL_PASS
  订阅地址   https://$DOMAIN/s/$TOKEN

下一步：
  1. 浏览器打开面板，点「添加节点」把第一台机器加进来
  2. 节点表非空后，跑 /opt/web/rotate.sh 重新生成订阅源
  3. 手机用订阅地址导入

还差什么：
  - subconverter-ng 必须手动装（见 docs/DEPLOY.md）
  - 云厂商自动化（开端口/看流量）是可选的，见 docs/DEPLOY.md 第 7 步
────────────────────────────────────────
EOF
