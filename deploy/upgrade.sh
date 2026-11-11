#!/usr/bin/env bash
# Evergreen · OwnLine 平滑升级脚本
# 运行环境：Debian 12+ / Ubuntu 22.04+ (root 权限)
set -euo pipefail

TARGET_VERSION="${1:-}"
REPO_URL="https://github.com/AdgaiWalker/VPN-OwnLine"
BRANCH="${LADDER_BRANCH:-main}"
WEB_DIR="/opt/web"
ROLLBACK_DIR="/opt/web.rollback"
TMP_DIR="$(mktemp -d /tmp/ownline-upgrade.XXXXXX)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> 开始执行 Evergreen · OwnLine 平滑升级..."

# 1. 检查权限
if [ "$(id -u)" != "0" ]; then
  echo "错误: 升级脚本需要 root 权限执行" >&2
  exit 1
fi

# 2. 拉取/下载目标版本代码
if command -v git >/dev/null 2>&1 && [ -d "$WEB_DIR/.git" ]; then
  echo "==> 检测到 Git 仓库，执行 git 更新..."
  cd "$WEB_DIR"
  git fetch --tags origin || true
  if [ -n "$TARGET_VERSION" ]; then
    git checkout "$TARGET_VERSION"
  else
    git checkout "$BRANCH" || true
    git pull origin "$BRANCH" || true
  fi
else
  echo "==> 正在下载最新发布包..."
  ARCHIVE_URL="$REPO_URL/archive/refs/heads/$BRANCH.tar.gz"

  found=0
  for prefix in '' 'https://ghproxy.net/' 'https://ghfast.top/'; do
    if curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 8 --max-time 120 "${prefix}${ARCHIVE_URL}" | tar xz -C "$TMP_DIR" --strip-components=1; then
      found=1
      break
    fi
  done

  if [ "$found" -ne 1 ]; then
    echo "错误: 无法下载目标版本，终止升级！" >&2
    exit 1
  fi

  # 3. 校验下载包关键完整性
  if [ ! -f "$TMP_DIR/server/admin.py" ] || [ ! -d "$TMP_DIR/server/nodekit" ]; then
    echo "错误: 下载的代码包缺少关键组件 (server/admin.py)，终止升级！" >&2
    exit 1
  fi

  # 4. 制作安全回滚快照
  if [ -d "$WEB_DIR" ]; then
    rm -rf "$ROLLBACK_DIR"
    cp -r "$WEB_DIR" "$ROLLBACK_DIR"
  fi

  # 5. 原子同步代码至 /opt/web（绝对不触碰 /opt/web-data）
  mkdir -p "$WEB_DIR"
  if [ -d "$TMP_DIR/server/providers" ]; then cp -r "$TMP_DIR/server/providers" "$WEB_DIR/"; fi
  if [ -d "$TMP_DIR/server/nodekit" ]; then cp -r "$TMP_DIR/server/nodekit" "$WEB_DIR/"; fi
  cp "$TMP_DIR/server"/*.py "$WEB_DIR/" 2>/dev/null || true
  cp "$TMP_DIR/server"/*.sh "$WEB_DIR/" 2>/dev/null || true
  if [ -f "$TMP_DIR/web/index.html" ]; then cp "$TMP_DIR/web/index.html" "$WEB_DIR/"; fi
  if [ -f "$TMP_DIR/web/change-password.html" ]; then cp "$TMP_DIR/web/change-password.html" "$WEB_DIR/"; fi
  if [ -f "$TMP_DIR/web/backup-crypto.js" ]; then cp "$TMP_DIR/web/backup-crypto.js" "$WEB_DIR/"; fi
  if [ -d "$TMP_DIR/web/assets" ]; then cp -r "$TMP_DIR/web/assets" "$WEB_DIR/"; fi
  if [ -d "$TMP_DIR/deploy" ]; then cp -r "$TMP_DIR/deploy" "$WEB_DIR/"; fi
  if [ -d "$TMP_DIR/scripts" ]; then cp -r "$TMP_DIR/scripts" "$WEB_DIR/"; fi
  chmod 755 "$WEB_DIR"/*.sh "$WEB_DIR"/*.py 2>/dev/null || true
fi

# 6. 平滑重启 admin.service
echo "==> 重启 admin.service..."
if command -v systemctl >/dev/null 2>&1; then
  systemctl restart admin.service || true
fi

# 7. 健康检查自检（探活 10 秒）
echo "==> 执行升级健康自检..."
HEALTHY=0
for i in 1 2 3 4 5; do
  sleep 1
  if curl -fsSL -k --max-time 3 http://127.0.0.1:8099/api/system/version >/dev/null 2>&1 || curl -fsSL -k --max-time 3 http://127.0.0.1:8000/api/system/version >/dev/null 2>&1; then
    HEALTHY=1
    break
  fi
done

if [ "$HEALTHY" -eq 1 ]; then
  echo "==> 升级成功，系统服务健康！"
  rm -rf "$ROLLBACK_DIR"
else
  echo "警告: 自检未通过，正在自动回滚至上一个版本..." >&2
  if [ -d "$ROLLBACK_DIR" ]; then
    rm -rf "$WEB_DIR"
    mv "$ROLLBACK_DIR" "$WEB_DIR"
    if command -v systemctl >/dev/null 2>&1; then
      systemctl restart admin.service || true
    fi
  fi
  exit 1
fi
