#!/usr/bin/env bash
# Stage and verify a complete official release before switching the runtime.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# A stable recovery entry point and timer are established before any exchange.
exec python3 "$SCRIPT_DIR/release.py" --prepare "${1:-latest}"
