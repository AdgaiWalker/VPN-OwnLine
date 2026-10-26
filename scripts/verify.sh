#!/usr/bin/env bash
# 一条命令验收。用法：
#   ./verify.sh https://v.example.com 用户名 密码 <订阅token>
set -uo pipefail
BASE="${1:?用法: verify.sh https://域名 用户名 密码 token}"
USER="${2:?缺用户名}"
PASS="${3:?缺密码}"
TOK="${4:?缺订阅 token}"

ok=0; bad=0
chk() { # 名称 期望 实际
  if [ "$2" = "$3" ]; then printf '  ✅ %-28s %s\n' "$1" "$3"; ok=$((ok+1));
  else printf '  ❌ %-28s 期望 %s，实际 %s\n' "$1" "$2" "$3"; bad=$((bad+1)); fi
}

echo "== 1. 访问控制 =="
chk "页面无密码" 401 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$BASE/")"
chk "页面有密码" 200 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 -u "$USER:$PASS" "$BASE/")"
chk "/sub 直连"   404 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$BASE/sub")"
chk "猜测 token"  404 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$BASE/s/0000000000")"

echo "== 2. 订阅 =="
CLASH="$(curl -s -m 20 -A 'ClashforWindows' "$BASE/s/$TOK")"
N1=$(printf '%s' "$CLASH" | grep -c 'reality-opts')
N2=$(curl -s -m 20 "$BASE/s/$TOK" | base64 -d 2>/dev/null | grep -c '^vless://')
if [ "$N1" -gt 0 ]; then printf '  ✅ clash 节点数 %s\n' "$N1"; ok=$((ok+1)); else printf '  ❌ clash 无可用的 reality 配置\n'; bad=$((bad+1)); fi
if [ "$N2" -gt 0 ]; then printf '  ✅ v2ray 节点数 %s\n' "$N2"; ok=$((ok+1)); else printf '  ❌ v2ray 解析失败\n'; bad=$((bad+1)); fi
if [ "$N1" = "$N2" ]; then printf '  ✅ 两种格式节点数一致\n'; ok=$((ok+1)); else printf '  ❌ 两种格式数量不一致 (%s vs %s)\n' "$N1" "$N2"; bad=$((bad+1)); fi

echo "== 3. 接口 =="
chk "节点接口" 200 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 -u "$USER:$PASS" "$BASE/api/nodes")"
chk "探活数据" 200 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 -u "$USER:$PASS" "$BASE/status.json")"
chk "接口无认证" 401 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 "$BASE/api/nodes")"

echo "== 4. 输入校验 =="
chk "非法地址" 400 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 -u "$USER:$PASS" -X POST -H 'Content-Type: application/json' -d '{"ip":"not-an-ip","pass":"x","name":"t"}' "$BASE/api/addnode")"

echo "== 5. 节点模型 =="
NODES_JSON="$(curl -s -m 20 -u "$USER:$PASS" "$BASE/api/nodes")"
TOTAL=$(printf '%s' "$NODES_JSON" | python3 -c 'import sys,json;print(len(json.load(sys.stdin)))')
ADV=$(printf '%s' "$NODES_JSON" | python3 -c 'import sys,json;print(sum(1 for n in json.load(sys.stdin) if n.get("advice")))')
chk "每个节点都有建议" "$TOTAL" "$ADV"
UNIQ=$(printf '%s' "$NODES_JSON" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(len({(n["host"],str(n["port"])) for n in d}))')
chk "主机端口不重复" "$TOTAL" "$UNIQ"
RELAYS=$(printf '%s' "$NODES_JSON" | python3 -c 'import sys,json;print(" ".join(n["host"] for n in json.load(sys.stdin) if (n.get("role") or "exit")=="relay"))')
LEAK=0
for h in $RELAYS; do printf '%s' "$CLASH" | grep -q "$h" && LEAK=$((LEAK+1)); done
chk "中转不进订阅" 0 "$LEAK"

echo "== 6. 新接口 =="
chk "粘贴空链接" 400 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 -u "$USER:$PASS" -X POST -H 'Content-Type: application/json' -d '{"links":""}' "$BASE/api/paste")"
chk "验证不存在节点" 404 "$(curl -s -o /dev/null -w '%{http_code}' -m 15 -u "$USER:$PASS" -X POST -H 'Content-Type: application/json' -d '{"name":"__nope__"}' "$BASE/api/verify")"
ROT="$(curl -s -m 15 -u "$USER:$PASS" -X POST -H 'Content-Type: application/json' -d '{"dry_run":true}' "$BASE/api/rotate")"
if printf '%s' "$ROT" | grep -q '不受影响'; then printf '  ✅ %-28s %s\n' "轮换演练有提示" "ok"; ok=$((ok+1)); else printf '  ❌ 轮换演练没返回提示\n'; bad=$((bad+1)); fi

echo
printf '结果：%d 通过，%d 失败\n' "$ok" "$bad"
[ "$bad" = 0 ] || exit 1
