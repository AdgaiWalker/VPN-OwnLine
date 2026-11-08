#!/usr/bin/env bash
# 跑全部本地测试门禁（全离网，零侵入，不碰生产）。
#
# 包含：
#   1. server/nodekit/ 核心业务套件 (16 套离线单测)
#   2. tests/test_*.py 综合回归与集成测试 (30 项 unittest)
#   3. tests/*.test.js 前端 UI、交互与加密单元测试 (27 项 Node.js 测试)
#   4. Shell 脚本语法与 Bash 3.2 空数组兼容性静态门禁
#
# 任何一项失败都退出非 0。

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="python3"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
fi

echo "========================================="
echo " Evergreen · OwnLine 自动化全量门禁"
echo " Python 解释器: $PYTHON_BIN"
echo "========================================="

total=0
failed=0

echo
echo "--- [1/4] 运行 server/nodekit 独立单测套件 ---"
for f in \
  server/nodekit/tests.py \
  server/nodekit/verify_tests.py \
  server/nodekit/advise_tests.py \
  server/nodekit/hints_tests.py \
  server/nodekit/templates_tests.py \
  server/nodekit/subscriptions_tests.py \
  server/nodekit/logger_tests.py \
  server/nodekit/repair_tests.py \
  server/nodekit/jev_tests.py \
  server/nodekit/lifecycle_tests.py \
  server/nodekit/relay_guard_tests.py \
  server/nodekit/quota_guard_tests.py \
  server/nodekit/quota_api_tests.py \
  server/nodekit/remote_config_tests.py \
  server/nodekit/host_traffic_tests.py \
  server/nodekit/ports_tests.py \
  server/nodekit/http_utils_tests.py \
  server/nodekit/relay_service_tests.py \
  server/nodekit/hy2_service_tests.py \
  server/nodekit/node_service_tests.py
do
  if out="$("$PYTHON_BIN" "$f" 2>&1)"; then
    n="$(printf '%s\n' "$out" | sed -n -e 's/^通过 \([0-9][0-9]*\) 项$/\1/p' -e 's/^Ran \([0-9][0-9]*\) test.*/\1/p' | tail -1)"
    n="${n:-0}"
    total=$((total + n))
    printf '  ✅ %-40s %s 项通过\n' "$f" "$n"
  else
    printf '  ❌ %-40s 失败\n' "$f"
    printf '%s\n' "$out" | tail -5 | sed 's/^/     /'
    failed=$((failed + 1))
  fi
done

echo
echo "--- [2/4] 运行 tests/ 自动化回归套件 (unittest) ---"
if out="$("$PYTHON_BIN" -m unittest discover -s tests -p "test_*.py" 2>&1)"; then
  n="$(printf '%s\n' "$out" | sed -n 's/^Ran \([0-9][0-9]*\) tests in.*/\1/p' | tail -1)"
  n="${n:-0}"
  total=$((total + n))
  printf '  ✅ %-40s %s 项通过\n' "tests/test_*.py" "$n"
else
  printf '  ❌ %-40s 失败\n' "tests/test_*.py"
  printf '%s\n' "$out" | tail -10 | sed 's/^/     /'
  failed=$((failed + 1))
fi

echo
echo "--- [3/4] 运行 tests/ 前端与加密单元测试 (Node.js) ---"
if command -v node >/dev/null 2>&1; then
  if out="$(node --test tests/*.test.js 2>&1)"; then
    n="$(printf '%s\n' "$out" | sed -n 's/^ℹ pass \([0-9][0-9]*\)$/\1/p' | tail -1)"
    n="${n:-0}"
    total=$((total + n))
    printf '  ✅ %-40s %s 项通过\n' "tests/*.test.js" "$n"
  else
    printf '  ❌ %-40s 失败\n' "tests/*.test.js"
    printf '%s\n' "$out" | tail -10 | sed 's/^/     /'
    failed=$((failed + 1))
  fi
else
  echo "  ⚠️ 未检测到 node 命令，跳过 JS 单元测试。"
fi

echo
echo "--- [4/4] 运行 Shell 脚本语法与 Bash 3.2 兼容性校验 ---"
sh_failed=0
for sh in deploy/*.sh server/*.sh scripts/*.sh; do
  if [ -f "$sh" ]; then
    if /bin/bash -n "$sh" 2>/dev/null; then
      printf '  ✅ 语法正确: %s\n' "$sh"
    else
      printf '  ❌ 语法错误: %s\n' "$sh"
      sh_failed=$((sh_failed + 1))
    fi
  fi
done

# macOS Bash 3.2 空数组 expand 崩溃特异性防回退测试
if /bin/bash -c 'set -eu; FORWARD_ARGS=(); /bin/bash -c "set -eu; args=(\"\${FORWARD_ARGS[@]+\"\${FORWARD_ARGS[@]}\"}\"); echo \${#args[@]}"' >/dev/null 2>&1; then
  printf '  ✅ Bash 3.2 空数组兼容性检验通过\n'
else
  printf '  ❌ Bash 3.2 空数组兼容性检验失败\n'
  sh_failed=$((sh_failed + 1))
fi

if [ "$sh_failed" -ne 0 ]; then
  failed=$((failed + sh_failed))
fi

echo
echo "========================================="
if [ "$failed" -ne 0 ]; then
  echo " ❌ 测试门禁未通过：$failed 项失败，共通过 $total 项测试"
  exit 1
fi
echo " ✅ 全部门禁通过！累计通过 $total 项单测/集成校验，脚本语法全绿"
echo "========================================="
