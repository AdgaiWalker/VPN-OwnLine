#!/usr/bin/env bash
# 跑全部本地单测（全离网，不碰生产）。
#
# 用法：
#   ./scripts/test.sh
#
# 任何一套失败都退出非 0。这是「72 项全过」这类说法唯一的证据来源——
# 文档里的数字会过期，这条命令不会。
set -u
cd "$(dirname "$0")/.." || exit 1

total=0
failed=0

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
  server/nodekit/ports_tests.py
do
  out="$(python3 "$f" 2>&1)"
  if [ $? -ne 0 ]; then
    printf '  ❌ %-38s 失败\n' "$f"
    printf '%s\n' "$out" | tail -5 | sed 's/^/     /'
    failed=$((failed + 1))
    continue
  fi
  n="$(printf '%s\n' "$out" | sed -n 's/^通过 \([0-9][0-9]*\) 项$/\1/p' | tail -1)"
  n="${n:-0}"
  total=$((total + n))
  printf '  ✅ %-38s %s 项\n' "$f" "$n"
done

echo
if [ "$failed" -ne 0 ]; then
  echo "结果：$failed 套失败，$total 项通过"
  exit 1
fi
echo "结果：$((12 + 1)) 套全过，$total 项通过"
