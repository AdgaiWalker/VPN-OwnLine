#!/usr/bin/env bash
# 一键自举脚本：下载仓库并执行 deploy/install.sh
set -euo pipefail

if [ "$(id -u)" != "0" ]; then
  echo "错误: 请用 root 权限运行 (sudo bash)" >&2
  exit 1
fi

BRANCH="${LADDER_BRANCH:-main}"
REPO_URL="https://github.com/AdgaiWalker/VPN-OwnLine"
TMP_DIR="$(mktemp -d /tmp/ladder-bootstrap.XXXXXX)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> 正在下载 VPN-OwnLine 部署包 ($BRANCH) ..."
if command -v git >/dev/null 2>&1; then
  git clone --depth=1 -b "$BRANCH" "$REPO_URL.git" "$TMP_DIR/ladder"
else
  mkdir -p "$TMP_DIR/ladder"
  curl -fsSL "$REPO_URL/archive/refs/heads/$BRANCH.tar.gz" | tar xz -C "$TMP_DIR/ladder" --strip-components=1
fi

chmod +x "$TMP_DIR/ladder/deploy/install.sh"
"$TMP_DIR/ladder/deploy/install.sh" "$@"
