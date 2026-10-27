"""verify 测试：真实网络，只读。重点是「假参数必须被识破」。"""
import json
import sys

sys.path.insert(0, "/opt/web")
from nodekit import verify

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


nodes = json.load(open("/opt/web/nodes.json", encoding="utf-8"))
sv = next(n for n in nodes if n["name"] == "硅谷")
relay = next(n for n in nodes if n["name"].endswith("（中转）"))

check("is_ip 正常", verify.is_ip("1.2.3.4"))
check("is_ip 拒绝域名", not verify.is_ip("example.com"))
check("tcp 通", verify.tcp_ok(sv["host"], sv["port"]))
check("tcp 不通（关闭端口）", not verify.tcp_ok(sv["host"], 65001, timeout=3))
check("tls 真握手", verify.tls_ok(sv["host"], sv["port"], sv["sni"]))
check("tls 拒绝普通 HTTP", not verify.tls_ok("198.51.100.13", 80, "www.apple.com"))

r = verify.run(sv)
check("出口节点：真实代理可用", r["health"] == "ok", r)
check("出口 IP 正确", r.get("exit_ip") == sv["host"], r)
check("出口国家 US", r.get("exit_country") == "US", r)

r = verify.run(relay)
check("中转：经落地出网", r["health"] == "ok" and "经落地" in r.get("detail", ""), r)

fake_uuid = dict(sv, uuid="00000000-0000-4000-8000-000000000000")
check("假 uuid 被识破", verify.run(fake_uuid)["health"] == "proxy", verify.run(fake_uuid))

fake_sid = dict(sv, sid="00000000")
check("假 sid 被识破", verify.run(fake_sid)["health"] == "proxy")

check("端口不通判 port", verify.run({"host": sv["host"], "port": 65002, "sni": "x"})["health"] == "port")
check("普通 HTTP 判 tls", verify.run({"host": "198.51.100.13", "port": 80, "sni": "www.apple.com", "role": "exit"})["health"] == "tls")

print("通过 %d 项" % ok)
