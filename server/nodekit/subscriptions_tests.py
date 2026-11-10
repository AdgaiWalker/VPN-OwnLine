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

# 禁用与到期自动剔除（防止停机黑洞故障）
check("enabled=False 不进订阅", not S.in_subscription({"health": "ok", "enabled": False}))
check("enabled=True 进订阅", S.in_subscription({"health": "ok", "enabled": True}))
check("已过期节点自动剔除", not S.in_subscription({"health": "ok", "expire_at": "2020-01-01T00:00:00Z"}))
check("未到期节点正常保留", S.in_subscription({"health": "ok", "expire_at": "2099-01-01T00:00:00Z"}))
check("时间戳格式已过期剔除", not S.in_subscription({"health": "ok", "expire_at": 1500000000}, now_ts=1700000000))
check("时间戳格式未过期保留", S.in_subscription({"health": "ok", "expire_at": 1900000000}, now_ts=1700000000))

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
import urllib.parse as _u
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

# 测试分客群 profile 适配
# 1. office 模式
yaml_office = S.render_clash_yaml(all_nodes, profile="office")
check("office 模式包含安全办公分组", "🛡️ 安全办公" in yaml_office, yaml_office)
check("office 模式包含微信防封号直连规则", "DOMAIN-KEYWORD,wechat,DIRECT" in yaml_office, yaml_office)

# 2. lite 模式
yaml_lite = S.render_clash_yaml(all_nodes, profile="lite")
check("lite 模式包含智能优选单分组", "🚀 智能优选" in yaml_lite, yaml_lite)
check("lite 模式隐藏了节点选择多选组", "节点选择" not in yaml_lite, yaml_lite)

# 3. direct 模式（纯直连过滤中继）
nodes_with_relay = [fast, relay, hy2_node]
yaml_direct = S.render_clash_yaml(nodes_with_relay, profile="direct")
check("direct 模式过滤掉了中继节点", "relay" not in yaml_direct, yaml_direct)
check("direct 模式保留了直连出口", "fast" in yaml_direct, yaml_direct)

b64_direct = S.render_v2ray_base64(nodes_with_relay, profile="direct")
decoded_direct = _b64.b64decode(b64_direct).decode("utf-8")
check("Base64 direct 模式过滤中继只留出口", "relay" not in decoded_direct and "fast" in decoded_direct, decoded_direct)

# 4. 到期动态预警名称（订阅即通知中心）
now = 1762905600.0  # 基准时间
n_normal = node("硅谷出口")
n_safe = node("远期出口", expire_at=now + 86400 * 15)
n_warn = node("临期出口", expire_at=now + 86400 * 3)
n_urgent = node("明到期出口", expire_at=now + 86400 * 1)
n_exp = node("过期出口", expire_at=now - 100)

check("无到期时间原样展示", S.format_display_name(n_normal, now_ts=now) == "硅谷出口")
check("远期节点原样展示", S.format_display_name(n_safe, now_ts=now) == "远期出口")
check("3天到期前缀报警", S.format_display_name(n_warn, now_ts=now) == "【剩3天到期】临期出口")
check("1天到期最高危报警", S.format_display_name(n_urgent, now_ts=now) == "【⚠️明天到期!】明到期出口")
check("过期节点前缀标记", S.format_display_name(n_exp, now_ts=now) == "【已过期】过期出口")

# 在 Clash 与 Base64 中验证动态报警前缀注入
clash_warn = S.render_clash_yaml([n_warn], now_ts=now)
check("Clash 中包含【剩3天到期】", "【剩3天到期】临期出口" in clash_warn)

v2ray_warn = S.render_v2ray_base64([n_warn], now_ts=now)
decoded_warn = _b64.b64decode(v2ray_warn).decode("utf-8")
check("Base64 中解码包含【剩3天到期】", "【剩3天到期】临期出口" in _u.unquote(decoded_warn))

# 5. 流量 85% 熔断安全锁过滤（防止产生超额账单扣费）
node_safe_quota = node("未超标节点", host="1.1.1.1")
node_tripped_quota = node("超标85%中转机", host="2.2.2.2")
node_safe_quota["quota_control_managed"] = True
node_tripped_quota["quota_control_managed"] = True
usage_mock = {
    "_ts": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    "1.1.1.1": {"used": 200.0, "total": 500.0},
    "2.2.2.2": {"used": 450.0, "total": 500.0},
}
check("未超标节点正常进订阅", S.in_subscription(node_safe_quota, usage_data=usage_mock))
check("超标85%节点自动熔断剔除", not S.in_subscription(node_tripped_quota, usage_data=usage_mock))

quota_nodes = [node_safe_quota, node_tripped_quota]
clash_quota = S.render_clash_yaml(quota_nodes, usage_data=usage_mock)
check("Clash 中保留未超标节点", "未超标节点" in clash_quota)
check("Clash 中自动熔断剔除超标节点", "超标85%中转机" not in clash_quota)

v2ray_quota = S.render_v2ray_base64(quota_nodes, usage_data=usage_mock)
decoded_quota = _b64.b64decode(v2ray_quota).decode("utf-8")
check("Base64 中保留未超标节点", "未超标节点" in _u.unquote(decoded_quota))
check("Base64 中自动熔断剔除超标节点", "超标85%中转机" not in _u.unquote(decoded_quota))

mixed_managed = node("同机受控记录", host="2.2.2.2")
mixed_managed["quota_control_managed"] = True
mixed_unverified = node("同机未确认记录", host="2.2.2.2")
mixed_nodes = [mixed_managed, mixed_unverified]
mixed_clash = S.render_clash_yaml(mixed_nodes, usage_data=usage_mock)
check("混合归属时 Clash 保留所有记录", "同机受控记录" in mixed_clash and "同机未确认记录" in mixed_clash)
mixed_b64 = _u.unquote(_b64.b64decode(S.render_v2ray_base64(mixed_nodes, usage_data=usage_mock)).decode())
check("混合归属时 Base64 保留所有记录", "同机受控记录" in mixed_b64 and "同机未确认记录" in mixed_b64)

# Subscription-Userinfo 响应头测试
u_hdr = S.subscription_userinfo(usage_mock)
check("Subscription-Userinfo 头部生成成功", bool(u_hdr))
check("Subscription-Userinfo 包含 upload", "upload=0" in u_hdr)
check("Subscription-Userinfo 包含精确 download 字节", "download=" + str(int(650.0 * 1024 * 1024 * 1024)) in u_hdr)
check("Subscription-Userinfo 包含精确 total 字节", "total=" + str(int(1000.0 * 1024 * 1024 * 1024)) in u_hdr)

usage_with_expire = {
    "1.1.1.1": {"used": 10.0, "total": 100.0, "expire": "2026-11-12"},
    "2.2.2.2": {"used": 20.0, "total": 100.0, "expire": "2027-10-24"},
}
u_exp_hdr = S.subscription_userinfo(usage_with_expire)
check("带到期日期的 Subscription-Userinfo 包含 expire 时间戳", "expire=" in u_exp_hdr)
check("空或无效用量返回 None", S.subscription_userinfo(None) is None and S.subscription_userinfo({}) is None)

# AI 分流组测试（按 01-PRD 客户端仅支持 Shadowrocket / Clash / FL Clash，不输出 sing-box JSON）
check("Clash 中包含 🤖 AI 业务 分组", "🤖 AI 业务" in yaml_str)
check("Clash 中包含 openai 规则路由至 AI 分组", "DOMAIN-KEYWORD,openai,🤖 AI 业务" in yaml_str)
check("Clash 顶部包含受控节点 IP 直连豁免规则", "IP-CIDR,1.2.3.4/32,DIRECT,no-resolve" in yaml_str)
check("已移除废弃的 Sing-box 客户端配置导出函数", not hasattr(S, "render_singbox_json"))

# 7. 人话专线命名与出海真实流量过滤测试
n_bj = node("北京", role="relay", host="198.51.100.10")
n_sv = node("硅谷", role="exit", host="203.0.113.10")
n_sg = node("新加坡", role="exit", host="203.0.113.20")
check("北京中继人话专线化", "北京专线 ➔ 🇺🇸 硅谷" in S.format_display_name(n_bj))
n_bj_sa = node("北京", role="standalone", host="198.51.100.10")
check("北京独立服务器人话显示", "国内独立服务器" in S.format_display_name(n_bj_sa))
check("硅谷直连人话专线化", "硅谷直连" in S.format_display_name(n_sv))

real_usage = {
    "203.0.113.10": {"used": 155.5, "total": 512.0},
    "203.0.113.20": {"used": 1.2, "total": 1024.0},
    "198.51.100.10": {"used": 0.7, "total": 500.0},
}
u_filtered = S.subscription_userinfo(real_usage, nodes=[n_bj, n_sv, n_sg])
# 仅统计 155.5 + 1.2 = 156.7 GB，而不是加上中继机的 157.4 GB；总额 512 + 1024 = 1536 GB，而不是 2036 GB
check("Subscription-Userinfo 过滤掉国内中继跳板流量", "download=" + str(int(156.7 * 1024 * 1024 * 1024)) in u_filtered)
check("Subscription-Userinfo 总额仅统计境外出口", "total=" + str(int(1536.0 * 1024 * 1024 * 1024)) in u_filtered)

print("通过 %d 项" % ok)
