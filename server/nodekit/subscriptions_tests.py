"""subscriptions 单元测试：全离网，纯断言。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import subscriptions as S

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


def node(name, **kw):
    base = {
        "name": name, "health": "ok", "role": "exit", "source": "builtin",
        "exit_country": "US", "host": "1.2.3.4", "port": 443,
        "uuid": "11111111-1111-4111-8111-111111111111",
        "pbk": "PUB", "sid": "abcd1234", "sni": "www.apple.com",
    }
    base.update(kw)
    return base


# 订阅过滤
for health in ("ok", "unknown", None):
    check("health=%s 进订阅" % health, S.in_subscription({"health": health}))
for health in ("port", "tls", "proxy", "role_mismatch", "landing", "blocked", "timeout"):
    check("health=%s 不进订阅" % health, not S.in_subscription({"health": health}))

# 自动借道：选最快、排除不可用/国内/中转/外部/缺字段
fast = node("fast")
slow = node("slow")
cn = node("cn", exit_country="CN")
bad = node("bad", health="port")
relay = node("relay", role="relay")
external = node("external", source="external")
missing = node("missing", pbk="")
status = {"fast": {"ms": 80}, "slow": {"ms": 300}, "cn": {"ms": 20},
          "bad": {"ms": 10}, "relay": {"ms": 5}, "external": {"ms": 1},
          "missing": {"ms": 2}}
picked = S.pick_landing([slow, fast, cn, bad, relay, external, missing], status)
check("选最快的可用海外出口", picked and picked["host"] == "1.2.3.4", picked)
check("借道参数完整", picked and set(picked) == {"host", "port", "uuid", "pbk", "sid", "sni"}, picked)
check("没有候选返回 None", S.pick_landing([cn, bad, relay, external], status) is None)
check("空列表不崩", S.pick_landing([], {}) is None)

# ---------- 内置订阅生成（V2Ray Base64 + Clash YAML） ----------
hy2_node = {
    "name": "硅谷-HY2", "type": "hysteria2", "health": "ok",
    "host": "198.51.100.12", "port": 443, "password": "PW", "sni": "www.bing.com",
    "obfs_password": "OBFS",
}
all_nodes = [fast, hy2_node, bad]  # bad 会被过滤

b64 = S.render_v2ray_base64(all_nodes)
check("Base64 输出非空", bool(b64), b64)
import base64 as _b64
decoded = _b64.b64decode(b64).decode("utf-8")
check("Base64 解码过滤了 bad 节点（只剩 2 条）", len(decoded.strip().splitlines()) == 2, decoded)
check("Base64 解码含 vless://", "vless://" in decoded, decoded)
check("Base64 解码含 hysteria2://", "hysteria2://" in decoded, decoded)

yaml_str = S.render_clash_yaml(all_nodes)
check("Clash YAML 输出非空", bool(yaml_str), yaml_str)
check("Clash YAML 包含 fast 与 硅谷-HY2", "fast" in yaml_str and "硅谷-HY2" in yaml_str, yaml_str)
check("Clash YAML 过滤了 bad 节点", "bad" not in yaml_str, yaml_str)
check("Clash YAML 含 type: hysteria2", "type: hysteria2" in yaml_str, yaml_str)
check("Clash YAML 含 type: vless", "type: vless" in yaml_str, yaml_str)
check("Clash YAML 含 url-test 自动选择", "type: url-test" in yaml_str, yaml_str)

print("通过 %d 项" % ok)
