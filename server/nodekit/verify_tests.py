"""verify 单元测试：全离网。

网络与 SSH 全部用桩替掉，只证明「状态机判得对不对」。
真机能不能通，由 `scripts/verify.sh` 在目标机上证明——这两件事不能互相替代。
重点是三条历史教训必须被代码守住：
  - 端口通 ≠ 服务在（普通 HTTP 也能 CONNECTED）
  - 握手成功 ≠ 能用（Reality 要看真实出口 IP）
  - 失败要落到具体 health，不能一句「失败了」
"""
import contextlib
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import verify as V

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


@contextlib.contextmanager
def stubbed(**fns):
    """临时替换 verify 模块里的函数，退出时还原。"""
    old = {name: getattr(V, name) for name in fns}
    try:
        for name, fn in fns.items():
            setattr(V, name, fn)
        yield
    finally:
        for name, fn in old.items():
            setattr(V, name, fn)


NODE = {"host": "198.51.100.12", "port": 443, "sni": "www.apple.com",
        "uuid": "11111111-1111-4111-8111-111111111111",
        "pbk": "PUBKEY", "sid": "87370495"}

# ---------- 纯函数 ----------
check("is_ip 正常", V.is_ip("1.2.3.4"))
check("is_ip 拒绝域名", not V.is_ip("example.com"))
check("is_ip 拒绝空串", not V.is_ip(""))


# ---------- tls_ok 的三种输出 ----------
class _SP:
    def __init__(self, out):
        self.stdout = out


def _tls(out):
    with stubbed(subprocess=types.SimpleNamespace(run=lambda *a, **k: _SP(out))):
        return V.tls_ok("198.51.100.12", 443, "www.apple.com")


check("tls 真握手 → True", _tls("CONNECTED\nCipher is TLS_AES_256_GCM_SHA384\n"))
check("普通 HTTP（只有 CONNECTED）→ False", not _tls("CONNECTED\n"))
check("握手失败 Cipher is (NONE) → False", not _tls("CONNECTED\nCipher is (NONE)\n"))

# ---------- run() 状态机 ----------
with stubbed(tcp_ok=lambda *a, **k: False):
    check("端口不通 → port", V.run(NODE)["health"] == "port", V.run(NODE))

with stubbed(tcp_ok=lambda *a, **k: True, tls_ok=lambda *a, **k: False):
    check("端口通但没握手 → tls", V.run(NODE)["health"] == "tls", V.run(NODE))

with stubbed(tcp_ok=lambda *a, **k: True, tls_ok=lambda *a, **k: True,
             proxy_exit_ip=lambda *a, **k: "203.0.113.9",
             country_of=lambda *a, **k: "US"):
    r = V.run(NODE)
    check("真出口 → ok", r["health"] == "ok", r)
    check("出口 IP 落库", r.get("exit_ip") == "203.0.113.9", r)
    check("出口国家落库", r.get("exit_country") == "US", r)

with stubbed(tcp_ok=lambda *a, **k: True, tls_ok=lambda *a, **k: True,
             proxy_exit_ip=lambda *a, **k: "198.51.100.7",
             country_of=lambda *a, **k: "CN"):
    r = V.run(NODE)
    check("出口在国内 → role_mismatch", r["health"] == "role_mismatch", r)

with stubbed(tcp_ok=lambda *a, **k: True, tls_ok=lambda *a, **k: True,
             proxy_exit_ip=lambda *a, **k: "",
             remote_exit_ip=lambda *a, **k: "203.0.113.9"):
    check("代理不通但 SSH 活着 → proxy", V.run(NODE)["health"] == "proxy", V.run(NODE))

with stubbed(tcp_ok=lambda *a, **k: True, tls_ok=lambda *a, **k: True,
             proxy_exit_ip=lambda *a, **k: "",
             remote_exit_ip=lambda *a, **k: ""):
    check("代理和 SSH 都不通 → blocked", V.run(NODE)["health"] == "blocked", V.run(NODE))

RELAY = dict(NODE, role="relay", landing={"host": "203.0.113.20", "port": 443})

with stubbed(tcp_ok=lambda *a, **k: True, tls_ok=lambda *a, **k: True,
             proxy_exit_ip=lambda *a, **k: "203.0.113.10",
             country_of=lambda *a, **k: "US"):
    r = V.run(RELAY)
    check("中转：真能出网 → ok", r["health"] == "ok" and "经落地" in r["detail"], r)

with stubbed(tcp_ok=lambda host, *a, **k: True, tls_ok=lambda *a, **k: True,
             proxy_exit_ip=lambda *a, **k: ""):
    check("中转：入口落地都通但代理不出去 → landing",
          V.run(RELAY)["health"] == "landing", V.run(RELAY))

with stubbed(tcp_ok=lambda host, *a, **k: host == NODE["host"], tls_ok=lambda *a, **k: True,
             proxy_exit_ip=lambda *a, **k: ""):
    check("中转：落地不可达 → proxy", V.run(RELAY)["health"] == "proxy", V.run(RELAY))

# ---------- 客户端配置 ----------
cfg = V._client_cfg(NODE, 23456)
ob = cfg["outbounds"][0]
check("客户端配置带 uuid", ob["uuid"] == NODE["uuid"], ob)
check("客户端配置开 reality", ob["tls"]["reality"]["enabled"] is True, ob)
check("客户端配置 socks 端口", cfg["inbounds"][0]["listen_port"] == 23456, cfg)

print("通过 %d 项" % ok)
