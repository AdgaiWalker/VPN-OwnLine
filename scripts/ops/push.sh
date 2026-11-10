#!/bin/bash
# 把本地 main 分支提交安全推送到 GitHub（可选推送指定 tag）。
# 用法：bash scripts/ops/push.sh [tag名]
# Token 通过临时 0700 GIT_ASKPASS 传递，不进进程命令行、不落盘保存。
set -euo pipefail
[ -z "${HOME:-}" ] && { HOME="/Users/$(id -un)"; export HOME; }

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OWNER="AdgaiWalker"
NAME="VPN-OwnLine"
REMOTE_URL="https://github.com/${OWNER}/${NAME}.git"
PUSH_TAG="${1:-}"

cd "$REPO"
echo "仓库：$OWNER/$NAME"
echo "待推提交："
git log --oneline origin/main..main 2>/dev/null | sed 's/^/  /' || true
echo

TOKEN="${GITHUB_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  read -rsp "粘贴 GitHub Personal Access Token（输入时不显示）: " TOKEN
  echo
fi
[ -z "$TOKEN" ] && { echo "没输入 token，退出"; exit 1; }

umask 077
ASKPASS_SCRIPT="$(mktemp -t ownline-askpass.XXXXXX)"
cleanup() {
  rm -f "$ASKPASS_SCRIPT"
}
trap cleanup EXIT INT TERM

cat > "$ASKPASS_SCRIPT" <<'EOF'
#!/bin/sh
case "$1" in
  *Username*) printf '%s\n' "${OWNLINE_GH_USER}" ;;
  *) printf '%s\n' "${OWNLINE_GH_TOKEN}" ;;
esac
EOF
chmod 700 "$ASKPASS_SCRIPT"

echo
echo "==> 推送 main"
OWNLINE_GH_USER="$OWNER" OWNLINE_GH_TOKEN="$TOKEN" GIT_ASKPASS="$ASKPASS_SCRIPT" GIT_TERMINAL_PROMPT=0 \
  git push "$REMOTE_URL" main

if [ -n "$PUSH_TAG" ]; then
  echo "==> 推送 tag $PUSH_TAG"
  OWNLINE_GH_USER="$OWNER" OWNLINE_GH_TOKEN="$TOKEN" GIT_ASKPASS="$ASKPASS_SCRIPT" GIT_TERMINAL_PROMPT=0 \
    git push "$REMOTE_URL" "$PUSH_TAG"
fi

echo
echo "✅ 推送完成。"
