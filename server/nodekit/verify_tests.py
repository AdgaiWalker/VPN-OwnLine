"""verify 模块测试：用真实网络，但只做只读检查。"""
import sys

sys.path.insert(0, "/opt/web")
from nodekit import verify

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


check("is_ip 正常", verify.is_ip("1.2.3.4"))
check("is_ip 拒绝域名", not verify.is_ip("example.com"))

check("tcp 通（硅谷 443）", verify.tcp_ok("198.51.100.12", 443))
check("tcp 不通（关闭端口）", not verify.tcp_ok("198.51.100.12", 65001, timeout=3))

r = verify.run({"host": "198.51.100.12", "port": 443, "sni": "www.apple.com", "role": "exit", "ssh_user": "ubuntu"})
check("出口节点 ok", r["health"] == "ok", r)
check("出口 IP 正确", r.get("exit_ip") == "198.51.100.12", r)
check("出口国家为 US", r.get("exit_country") == "US", r)

r2 = verify.run({"host": "198.51.100.13", "port": 443, "sni": "www.apple.com", "role": "exit"})
check("国内机选出口被识别", r2["health"] == "role_mismatch", r2)

r3 = verify.run({"host": "198.51.100.13", "port": 443, "sni": "www.apple.com", "role": "relay",
                 "landing": {"host": "198.51.100.12", "port": 443}})
check("中转：入口与落地都通", r3["health"] == "ok" and "落地" in r3.get("detail", ""), r3)

r4 = verify.run({"host": "198.51.100.13", "port": 443, "sni": "www.apple.com", "role": "relay",
                 "landing": {"host": "198.51.100.12", "port": 65002}})
check("中转：落地不通", r4["health"] == "landing", r4)

r5 = verify.run({"host": "198.51.100.12", "port": 65003, "sni": "x"})
check("端口不通", r5["health"] == "port", r5)

print("通过 %d 项" % ok)
