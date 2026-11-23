"""advise 单元测试：全离网，纯断言。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import advise as A

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, "失败: %s %s" % (name, extra)
    ok += 1
    print("  OK " + name)


sv = {"name": "硅谷", "health": "ok", "exit_country": "US"}
r = A.advise(sv, {"ok": True, "ms": 112}, {"used": 4.3, "total": 512})
check("快+美国 → AI 首选", r["text"] == "AI 首选", r)
check("依据含延迟", "112ms" in r["reason"], r)
check("依据含出口", "US" in r["reason"], r)
check("依据含流量", "4.3/512" in r["reason"], r)

sg = dict(sv, name="新加坡", exit_country="SG")
r = A.advise(sg, {"ms": 820}, None)
check("慢 → 能连但慢", r["text"] == "能连，但慢", r)

r = A.advise({"name": "广州", "health": "role_mismatch", "health_detail": "出口在中国"})
check("role_mismatch → 红", r["text"] == "出去还是国内 IP，帮不上忙" and r["level"] == "bad", r)

r = A.advise({"name": "落地坏", "health": "landing"})
check("landing → 连不上落地", r["text"] == "连不上落地" and r["level"] == "bad", r)

r = A.advise({"name": "外", "source": "external", "health": "unknown"})
check("外部 → 未验证", r["text"] == "外部节点，未验证" and r["level"] == "warn", r)

r = A.advise({"name": "堵", "health": "blocked"})
check("被墙 → 提示换 IP", r["text"] == "可能被墙了", r)

r = A.advise(sv, {"ms": 100}, {"used": 500, "total": 512})
check("流量 98% → 警告", r["text"] == "流量快用完" and r["level"] == "warn", r)

r = A.advise({"name": "新", "health": "unknown"}, None, None)
check("没探活 → 等待探测", r["text"] == "等待探测", r)

r = A.advise({"name": "代理坏", "health": "proxy"})
check("proxy → 红", r["text"] == "机器活着但代理不通" and r["level"] == "bad", r)

r = A.advise(dict(sv, exit_country="SG"), {"ms": 240}, None)
check("快+新加坡 → AI 首选", r["text"] == "AI 首选", r)

r = A.advise(dict(sv, exit_country=""), {"ms": 240}, None)
check("快+国家未知 → AI 首选", r["text"] == "AI 首选", r)

r = A.advise(dict(sv, exit_country="DE"), {"ms": 240}, None)
check("快+德国 → 日常可用", r["text"] == "日常可用", r)

r = A.advise(sv, {"ms": 450}, None)
check("中等延迟 → AI 偏慢", r["text"] == "日常可用，AI 偏慢" and r["level"] == "warn", r)

r = A.advise(sv, {"ms": None}, None)
check("有探活无延迟 → 日常可用", r["text"] == "日常可用" and r["level"] == "good", r)

r = A.advise(sv, {"ok": False, "reason": "port"}, None)
check("探活 ok=False → 红灯", r["level"] == "bad" and "端口" in r["text"], r)

r = A.advise(sv, {"ok": True, "ms": 25, "cn_ok": False, "cn_reason": "port"}, None)
check("海外通但国内不通 → 可能被墙", r["level"] == "bad" and "被墙" in r["text"], r)

r = A.advise(sv, {"ok": True, "ms": 25, "cn_ok": True, "cn_ms": 180}, None)
check("国内延迟进入依据", "国内 180ms" in r["reason"], r)
check("低延迟且无风险无 action", r.get("action") is None, r)

r = A.advise(dict(sv, hy2_enabled=False), {"ok": True, "ms": 80, "cn_ok": True, "cn_ms": 260}, None)
check("未开 HY2 + 高延迟触发 awaken_hy2", r.get("action") == "awaken_hy2" and r.get("action_hint"), r)

r = A.advise(dict(sv, hy2_enabled=True), {"ok": True, "ms": 90}, None, iphealth={"hosting": True, "proxy": False})
check("机房 IP 未挂家宽触发 mount_isp", r.get("action") == "mount_isp" and "住宅" in r.get("action_hint", ""), r)

r = A.advise(dict(sv, hy2_enabled=True, isp={"type": "socks", "server": "1.2.3.4", "server_port": 1080}), {"ok": True, "ms": 90}, None, iphealth={"hosting": True, "proxy": False})
check("已挂住宅 IP 不再重复触发 mount_isp", r.get("action") is None, r)

r = A.advise(dict(sv, hy2_enabled=True), {"ok": True, "ms": 120, "cn_ok": True, "cn_ms": 260}, None, nodes=[sv])
check("已开 HY2 仍高延迟且无中转触发 add_relay", r.get("action") == "add_relay" and "中转" in r.get("action_hint", ""), r)

r = A.advise(dict(sv, hy2_enabled=True), {"ok": True, "ms": 120, "cn_ok": True, "cn_ms": 260}, None, nodes=[sv, {"role": "relay", "country": "CN"}])
check("已有国内中转不再触发 add_relay", r.get("action") is None, r)

print("通过 %d 项" % ok)
