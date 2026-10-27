"""templates 单元测试：全离网，纯断言。

重点是 2026-10-27 新加的 Hysteria2 可选入站——它以前不在模板里，
导致硅谷的真实配置生成不出来，模板和线上悄悄脱节。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import templates as T

ok = 0

BASE = dict(port=443, uuid="11111111-1111-4111-8111-111111111111",
            sni="www.apple.com", private_key="PRIV", sid="87370495")
HY2 = dict(port=443, password="p@ss", obfs_password="obfs", sni="www.bing.com")


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


# --- 出口：不带 HY2 ---
c = T.exit_config(**BASE)
check("出口只有 1 个 inbound", len(c["inbounds"]) == 1)
check("出口 inbound 是 vless", c["inbounds"][0]["type"] == "vless")
check("出口出站只有 direct", [o["type"] for o in c["outbounds"]] == ["direct"])
check("出口没有 route", "route" not in c)

# --- 出口：带 HY2 ---
c2 = T.exit_config(hy2=HY2, **BASE)
check("带 HY2 有 2 个 inbound", len(c2["inbounds"]) == 2)
hy = c2["inbounds"][1]
check("第二个 inbound 是 hysteria2", hy["type"] == "hysteria2")
check("HY2 和 Reality 共用端口号", hy["listen_port"] == 443)
check("HY2 密码正确", hy["users"][0]["password"] == "p@ss")
check("HY2 混淆类型 salamander", hy["obfs"]["type"] == "salamander")
check("HY2 混淆密码正确", hy["obfs"]["password"] == "obfs")
check("HY2 ALPN 是 h3", hy["tls"]["alpn"] == ["h3"])
check("HY2 用自签证书路径", hy["tls"]["certificate_path"].endswith("hy2.crt"))
check("HY2 有上下行带宽提示", hy["up_mbps"] and hy["down_mbps"])

# --- 中转 ---
LAND = dict(host="1.2.3.4", port=443, uuid="22222222-2222-4222-8222-222222222222",
            sni="www.apple.com", pbk="PUB", sid="abcd1234")
r = T.relay_config(landing=LAND, **BASE)
check("中转有 landing 出站", any(o.get("tag") == "landing" for o in r["outbounds"]))
check("中转 route 全走 landing", r["route"]["rules"] == [{"outbound": "landing"}])
check("中转 landing 用 reality", r["outbounds"][0]["tls"]["reality"]["public_key"] == "PUB")

# --- validate ---
check("validate 接受出口配置", T.validate(c) == [])
check("validate 接受带 HY2 的配置", T.validate(c2) == [])
check("validate 接受中转配置", T.validate(r) == [])
bad = {"inbounds": [], "outbounds": []}
check("validate 拒绝空 inbound", len(T.validate(bad)) > 0)

print("通过 %d 项" % ok)
