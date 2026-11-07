#!/usr/bin/env bash
# ==============================================================================
# 长青 (Evergreen OwnLine) · Mac 本地一键装机与管理入口交付脚本
#
# 哲学：
#   “做成家用电饭煲，绝不做成飞机驾驶舱”
#   Mac 端零额外依赖（仅使用系统原生 bash、ssh、tar、open）
#   装机完成后自动解析受信任绿锁地址，秒级拉起 Mac 默认浏览器。
#
# 用法：
#   ./deploy/setup-mac.sh [服务器IP] [--domain 你的域名] [--dry-run]
#   例如：
#   ./deploy/setup-mac.sh 203.0.113.10
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✔ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✖ %s\033[0m\n' "$*" >&2; exit 1; }

TARGET_IP=""
SSH_USER="root"
SSH_PORT="22"
DOMAIN=""
DRY_RUN=0
FORWARD_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --user|-u)
      SSH_USER="$2"; shift 2 ;;
    --port|-p)
      SSH_PORT="$2"; shift 2 ;;
    --domain|-d)
      DOMAIN="$2"; FORWARD_ARGS+=("--domain" "$2"); shift 2 ;;
    --dry-run)
      DRY_RUN=1; FORWARD_ARGS+=("--dry-run"); shift ;;
    --help|-h)
      echo "用法: $0 [服务器IP] [--user root] [--port 22] [--domain 自定义域名] [--dry-run]"
      exit 0 ;;
    -*)
      FORWARD_ARGS+=("$1"); shift ;;
    *)
      if [ -z "${TARGET_IP}" ]; then
        TARGET_IP="$1"
      else
        FORWARD_ARGS+=("$1")
      fi
      shift ;;
  esac
done

say "长青 (Evergreen OwnLine) · 主控中枢自动化装配启动器"

if [ -z "${TARGET_IP}" ]; then
  printf '👉 请输入目标服务器公网 IP (例如 203.0.113.10): '
  read -r TARGET_IP
fi

[[ "${TARGET_IP}" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] || die "输入的公网 IP 格式不正确: ${TARGET_IP}"
[[ "${SSH_PORT}" =~ ^[0-9]{1,5}$ ]] && [ "${SSH_PORT}" -ge 1 ] && [ "${SSH_PORT}" -le 65535 ] || die "SSH 端口格式不正确: ${SSH_PORT}"

say "1/4 正在检查本地与目标机连通性 (${TARGET_IP}:${SSH_PORT})..."
if ! nc -z -G 3 "${TARGET_IP}" "${SSH_PORT}" 2>/dev/null; then
  warn "端口 ${SSH_PORT} 暂未探测到开放（若刚开机可能需等待 10~20 秒）。尝试通过 SSH 连接..."
fi

SSH_OPTS=(-p "${SSH_PORT}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 -o ServerAliveInterval=10)

say "2/4 正在连接服务器并同步装配安装包..."
TMP_REMOTE="/tmp/ownline-bootstrap-${RANDOM}-$$"
TMP_LOG=""
REMOTE_CREATED=0

cleanup() {
  if [ -n "${TMP_LOG}" ] && [ -f "${TMP_LOG}" ]; then
    rm -f "${TMP_LOG}"
  fi
  if [ "${REMOTE_CREATED}" = 1 ]; then
    ssh "${SSH_OPTS[@]}" "${SSH_USER}@${TARGET_IP}" "rm -rf '${TMP_REMOTE}'" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

BUNDLE_ITEMS=(deploy server web)
if [ -f "$REPO_DIR/requirements.lock" ]; then
  BUNDLE_ITEMS+=(requirements.lock)
fi

# 打包本地必要部署文件流式推送到目标机
tar -cz -C "$REPO_DIR" "${BUNDLE_ITEMS[@]}" | \
  ssh "${SSH_OPTS[@]}" "${SSH_USER}@${TARGET_IP}" \
  "umask 077 && mkdir -p '${TMP_REMOTE}' && tar -xz -C '${TMP_REMOTE}'" || die "无法通过 SSH 连接到目标服务器 ${TARGET_IP}，请检查用户名、密码或密钥。"
REMOTE_CREATED=1

ok "装配包已成功送达目标机"

say "3/4 正在远程执行静默装配流水线 (请稍候 1~2 分钟)..."
REMOTE_ARGS=""
for arg in ${FORWARD_ARGS[@]+"${FORWARD_ARGS[@]}"}; do
  REMOTE_ARGS="${REMOTE_ARGS} $(printf '%q' "$arg")"
done
INSTALL_CMD="cd '${TMP_REMOTE}' && sudo bash deploy/install.sh${REMOTE_ARGS}"

# 创建受限权限的临时文件捕获安装日志并实时展示（退出时由 trap 自动销毁）
umask_prev=$(umask)
umask 077
TMP_LOG="$(mktemp /tmp/ownline-setup-log.XXXXXX)"
umask "$umask_prev"
ssh -t "${SSH_OPTS[@]}" "${SSH_USER}@${TARGET_IP}" "${INSTALL_CMD}" | tee "${TMP_LOG}" || true

say "4/4 正在解析服务交付信息..."

MANAGEMENT_URL=$(grep -Eo 'https://[a-zA-Z0-9.-]+:8443/' "${TMP_LOG}" | tail -n 1 || true)
DELIVERY_VERIFIED=0
if grep -Fq "安装脚本执行完毕；请从其他设备确认管理页面可访问。" "${TMP_LOG}"; then
  DELIVERY_VERIFIED=1
fi
rm -f "${TMP_LOG}"
TMP_LOG=""

if [ "${DRY_RUN}" = 1 ]; then
  ok "演练模式执行完毕（未实际改动目标服务器）。"
elif [ -n "${MANAGEMENT_URL}" ] && [ "${DELIVERY_VERIFIED}" = 1 ]; then
  say "🎉 部署完成！你的专属安全控制中枢已通过本机验证："
  echo ""
  printf '  \033[1;32m👉 控制台入口: %s\033[0m\n' "${MANAGEMENT_URL}"
  echo "  （本机已验证 TLS 证书与鉴权响应，请妥善保存上方输出的管理密码）"
  echo ""
  if [ "$(uname)" = "Darwin" ] && command -v open >/dev/null 2>&1; then
    say "正在自动为您拉起默认浏览器..."
    open "${MANAGEMENT_URL}" || true
  fi
elif [ -n "${MANAGEMENT_URL}" ]; then
  warn "服务已安装，但管理入口尚未完成可信 TLS / 域名解析验证："
  printf '  候选入口: %s\n' "${MANAGEMENT_URL}"
  echo "  请检查云厂商安全组是否已放行 80/tcp、8443/tcp、443/tcp、443/udp，以及域名解析是否已生效。"
else
  warn "未在输出中解析到管理网址，请检查上方日志确认安装状态。"
fi
