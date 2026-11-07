#!/usr/bin/env bash
# 一键自举脚本：下载仓库并执行 deploy/install.sh
set -euo pipefail

if [ "$(id -u)" != "0" ]; then
  echo "错误: 请用 root 权限运行 (sudo bash)" >&2
  exit 1
fi

BRANCH="${LADDER_BRANCH:-main}"
REPO_URL="https://github.com/AdgaiWalker/VPN-OwnLine"
EXPECTED_COMMIT="${OWNLINE_COMMIT:-}"
EXPECTED_ARCHIVE_SHA="${OWNLINE_ARCHIVE_SHA256:-}"
TMP_DIR="$(mktemp -d /tmp/ladder-bootstrap.XXXXXX)"

cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> 正在下载 VPN-OwnLine 部署包 ($BRANCH) ..."
if [ -n "$EXPECTED_COMMIT" ] || [ -n "$EXPECTED_ARCHIVE_SHA" ]; then
  [[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ && "$EXPECTED_ARCHIVE_SHA" =~ ^[0-9a-f]{64}$ ]] || {
    echo "镜像下载需要可信来源提供的完整提交号与归档 SHA-256。" >&2; exit 2;
  }
  archive_url="$REPO_URL/archive/$EXPECTED_COMMIT.tar.gz"
  found=0
  for prefix in 'https://ghproxy.net/' 'https://ghfast.top/' ''; do
    if curl -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 8 --max-time 120 -o "$TMP_DIR/release.tar.gz" "${prefix}${archive_url}" &&
       [ "$(sha256sum "$TMP_DIR/release.tar.gz" | awk '{print $1}')" = "$EXPECTED_ARCHIVE_SHA" ]; then
      found=1; break
    fi
    echo "下载来源不可用或归档校验不符，尝试下一来源。" >&2
    rm -f "$TMP_DIR/release.tar.gz"
  done
  [ "$found" = 1 ] || { echo "无法下载匹配可信校验值的产品版本。" >&2; exit 1; }
  mkdir -p "$TMP_DIR/ladder"
  tar xzf "$TMP_DIR/release.tar.gz" -C "$TMP_DIR/ladder" --strip-components=1
elif command -v git >/dev/null 2>&1; then
  git -c http.connectTimeout=8 clone --depth=1 -b "$BRANCH" "$REPO_URL.git" "$TMP_DIR/ladder" || {
    echo "官方仓库不可用；镜像安装需先从可信发布渠道取得提交号和归档校验值。" >&2; exit 1;
  }
else
  mkdir -p "$TMP_DIR/ladder"
  curl -fsSL --proto '=https' --proto-redir '=https' "$REPO_URL/archive/refs/heads/$BRANCH.tar.gz" | tar xz -C "$TMP_DIR/ladder" --strip-components=1
fi

chmod +x "$TMP_DIR/ladder/deploy/install.sh"
"$TMP_DIR/ladder/deploy/install.sh" "$@"
