#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo '未找到可用的 Python 3.10+。'
  echo '建议直接下载免 Python 的 macOS 独立安装包（OwnLine-Setup-*-macOS-*.zip）：'
  echo '  https://github.com/AdgaiWalker/VPN-OwnLine/releases/latest'
  read -r -p '按回车退出。'
  exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))'; then
  echo '当前系统的 Python 版本低于 3.10。'
  echo '建议直接下载免 Python 的 macOS 独立安装包：'
  echo '  https://github.com/AdgaiWalker/VPN-OwnLine/releases/latest'
  read -r -p '按回车退出。'
  exit 1
fi
exec python3 -B ownline.py ui
