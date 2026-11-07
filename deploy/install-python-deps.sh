#!/usr/bin/env bash
# Install the control-plane's locked dependencies without changing global pip settings.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${1:-$ROOT/.venv/bin/python}"
TARGET="${2:-}"
LOCKFILE="${3:-$ROOT/requirements.lock}"
PIP_ARGS=(--no-input --disable-pip-version-check --timeout 10 --retries 1 --require-hashes -r "$LOCKFILE")
if [ -n "$TARGET" ]; then PIP_ARGS+=(--target "$TARGET" --upgrade); fi
for index in 'https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple' 'https://pypi.org/simple'; do
  if "$PYTHON" -m pip install "${PIP_ARGS[@]}" --index-url "$index"; then
    exit 0
  fi
  echo "依赖源暂不可用，正在尝试下一来源。" >&2
done
echo "无法安装经过校验的 Python 依赖，请检查网络后重试。" >&2
exit 1
