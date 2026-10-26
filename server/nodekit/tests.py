"""nodekit 单元测试：不依赖网络、不依赖 SSH，纯断言。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import links, preflight, templates

PASS = []


def ok(name, cond, extra=""):
    if cond:
        PASS.append(name)
    else:
        raise AssertionError("失败: %s %s" % (name, extra))


# ---------- preflight ----------
ok("ubuntu 22.04 支持", preflight.supported_os(*preflight.parse_os_release('ID=ubuntu\nVERSION_ID="22.04"'))[0])
ok("ubuntu 18.04 不支持", not preflight.supported_os(*preflight.parse_os_release('ID=ubuntu\nVERSION_ID="18.04"'))[0])
ok("debian 12 支持", preflight.supported_os(*preflight.parse_os_release('ID=debian\nVERSION_ID="12"'))[0])
ok("centos 7 不支持", not preflight.supported_os(*preflight.parse_os_release('ID=centos\nVERSION_ID="7"'))[0])
ok("rocky 9 支持", preflight.supported_os(*preflight.parse_os_release('ID=rocky\nVERSION_ID="9.3"'))[0])
ok("alpine 不支持", not preflight.supported_os(*preflight.parse_os_release('ID=alpine\nVERSION_ID="3.19"'))[0])
ok("arch x86_64", preflight.map_arch("x86_64") == "amd64")
ok("arch aarch64", preflight.map_arch("aarch64") == "arm64")
ok("arch armv7 不支持", preflight.map_arch("armv7l") is None)

probe = """ID=ubuntu
VERSION_ID="22.04"
---ARCH---
x86_64
---SYSTEMD---
/usr/bin/systemctl
---DISK---
/dev/vda1 41152736 8234567 5000 21% /
---TOOLS---
/usr/bin/curl
/usr/bin/tar
---INSTALLED---
no"""
info = preflight.parse_probe_output(probe)
ok("探测解析 arch", info["arch"] == "x86_64", info)
ok("探测解析 disk", info["disk_mb"] == 5000, info)
ok("探测解析 tools", info["curl"] == "yes" and info["tar"] == "yes", info)
ok("决策通过", preflight.decide(info)[0] is True, preflight.decide(info))

bad = dict(info, disk_mb=50)
ok("磁盘不足拒绝", preflight.decide(bad)[1] == "disk_low")
nosd = dict(info, systemd="none")
ok("无 systemd 拒绝", preflight.decide(nosd)[1] == "no_systemd")


# 国产 / 衍生发行版
ok("alinux 3 支持", preflight.supported_os(*preflight.parse_os_release('ID="alinux"\nVERSION_ID="3"'))[0])
ok("anolis 8 支持", preflight.supported_os(*preflight.parse_os_release('ID="anolis"\nVERSION_ID="8.8"'))[0])
ok("openeuler 22 支持", preflight.supported_os(*preflight.parse_os_release('ID="openEuler"\nVERSION_ID="22.03"'))[0])
d, v, fam = preflight.parse_os_release('ID="kali"\nID_LIKE="debian"\nVERSION_ID="2024.1"')
ok("ID_LIKE 兜底：kali → debian", fam == "debian" and preflight.supported_os(d, v, fam)[0], fam)
d2, v2, fam2 = preflight.parse_os_release('ID="mycustom"\nID_LIKE="rhel centos"\nVERSION_ID="9"')
ok("ID_LIKE 兜底：自定义 → rhel", fam2 == "rhel" and preflight.supported_os(d2, v2, fam2)[0], fam2)
ok("debian 10 不支持", not preflight.supported_os(*preflight.parse_os_release('ID=debian\nVERSION_ID="10"'))[0])

# ---------- links ----------
GOOD = ("vless://11111111-1111-4111-8111-111111111111@1.2.3.4:443"
        "?encryption=none&flow=xtls-rprx-vision&security=reality&sni=www.apple.com"
        "&fp=chrome&pbk=PUBKEY&sid=abcd1234&type=tcp#测试节点")
n = links.parse(GOOD)
ok("解析 host", n["host"] == "1.2.3.4")
ok("解析 port", n["port"] == 443)
ok("解析 name", n["name"] == "测试节点")
back = links.parse(links.build(n))
ok("round-trip", back["uuid"] == n["uuid"] and back["pbk"] == n["pbk"] and back["port"] == 443)

for broken, keyword in [
    (GOOD.replace("pbk=PUBKEY&", ""), "pbk"),
    (GOOD.replace("vless://", "vmess://"), "vless"),
    (GOOD.replace(":443", ":0"), "端口"),
    (GOOD.replace("security=reality", "security=tls"), "reality"),
]:
    try:
        links.parse(broken)
        raise AssertionError("应该报错但没有: " + broken[:40])
    except links.LinkError as e:
        ok("报错含关键词 " + keyword, keyword in str(e), str(e))

# ---------- templates ----------
cfg = templates.exit_config(443, "11111111-1111-4111-8111-111111111111", "www.apple.com", "PRIVKEY", "abcd1234")
ok("exit 无 vless outbound", all(o["type"] != "vless" for o in cfg["outbounds"]))
ok("exit 结构合法", templates.validate(cfg) == [], templates.validate(cfg))

landing = {"host": "5.6.7.8", "port": 443, "uuid": "22222222-2222-4222-8222-222222222222",
           "pbk": "PBK2", "sid": "ef01ab23", "sni": "www.microsoft.com"}
relay = templates.relay_config(443, "11111111-1111-4111-8111-111111111111", "www.apple.com", "PRIVKEY", "abcd1234", landing)
ok("relay 有 landing outbound", any(o.get("tag") == "landing" for o in relay["outbounds"]))
ok("relay 有路由规则", relay["route"]["rules"][0]["outbound"] == "landing")
ok("relay 结构合法", templates.validate(relay) == [], templates.validate(relay))

broken_cfg = templates.exit_config(443, "", "", "", "")
ok("校验能发现缺字段", len(templates.validate(broken_cfg)) >= 3, templates.validate(broken_cfg))


# sid 必须是十六进制
try:
    links.parse(GOOD.replace("sid=abcd1234", "sid=zzzz1234"))
    raise AssertionError("坏 sid 应该报错")
except links.LinkError as e:
    ok("坏 sid 被拒", "十六进制" in str(e), str(e))
bad_cfg = templates.exit_config(443, "11111111-1111-4111-8111-111111111111", "www.apple.com", "PRIVKEY", "zzzz")
ok("结构校验拦住坏 sid", any("十六进制" in x for x in templates.validate(bad_cfg)), templates.validate(bad_cfg))

print("通过 %d 项" % len(PASS))
for name in PASS:
    print("  OK " + name)
