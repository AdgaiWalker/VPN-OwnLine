"""verify 单元测试：把网络调用替换成桩，离线验证判定逻辑。

真机连通性由 scripts/verify.sh 和部署后的实际节点负责；这里只保证
“端口 / 握手 / 出口 / 落地 / 被墙”这些分支不会判断错。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import verify

ok = 0
ORIG = (verify.tcp_ok, verify.tls_ok, verify.proxy_exit_ip,
        verify.country_of, verify.remote_exit_ip)


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


def run_case(node, tcp=True, tls=True, proxy="", country="", remote=""):
    verify.tcp_ok = lambda *a, **k: tcp
    verify.tls_ok = lambda *a, **k: tls
    verify.proxy_exit_ip = lambda *a, **k: proxy
    verify.country_of = lambda *a, **k: country
    verify.remote_exit_ip = lambda *a, **k: remote
    try:
        return verify.run(node)
    finally:
        (verify.tcp_ok, verify.tls_ok, verify.proxy_exit_ip,
         verify.country_of, verify.remote_exit_ip) = ORIG


sv = {
    "name": "硅谷", "host": "1.2.3.4", "port": 443, "role": "exit",
    "uuid": "11111111-1111-4111-8111-111111111111",
    "pbk": "PUB", "sid": "abcd1234", "sni": "www.apple.com",
}

check("is_ip 正常", verify.is_ip("1.2.3.4"))
check("is_ip 拒绝域名", not verify.is_ip("example.com"))
check("端口不通判 port", run_case(sv, tcp=False)["health"] == "port")
check("握手失败判 tls", run_case(sv, tcp=True, tls=False)["health"] == "tls")
r = run_case(sv, proxy="203.0.113.9", country="US")
check("出口可用判 ok", r["health"] == "ok", r)
check("出口 IP 正确", r.get("exit_ip") == "203.0.113.9", r)
r = run_case(sv, proxy="1.2.3.4", country="CN")
check("出口在中国判 role_mismatch", r["health"] == "role_mismatch" and r["exit_ip"] == "1.2.3.4", r)

relay = dict(sv, name="广州", role="relay",
             landing={"host": "5.6.7.8", "port": 443, "uuid": "x", "pbk": "p", "sid": "s", "sni": "n"})
r = run_case(relay, proxy="203.0.113.9", country="US")
check("中转经落地出网判 ok", r["health"] == "ok" and "经落地" in r.get("detail", ""), r)
r = run_case(relay, proxy="", tcp=True, remote="")
check("落地不通判 landing", r["health"] == "landing", r)
r = run_case(relay, proxy="", tcp=False, remote="")
check("入口都不通判 port", r["health"] == "port", r)

r = run_case(sv, proxy="", remote="198.51.100.7")
check("代理坏但机器活着判 proxy", r["health"] == "proxy", r)
r = run_case(sv, proxy="", remote="")
check("代理和 SSH 都不通判 blocked", r["health"] == "blocked", r)

print("通过 %d 项" % ok)
