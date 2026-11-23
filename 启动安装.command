#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo '未找到 Python 3。请安装 Python 3.10 或更新版本后重新双击。'
  read -r -p '按回车退出。'
  exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  echo '需要 Python 3.10 或更新版本。'
  read -r -p '按回车退出。'
  exit 1
fi
exec python3 -B ownline.py ui
