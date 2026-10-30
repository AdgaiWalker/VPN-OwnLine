"""订阅过滤与自动借道选择：纯函数，不读文件、不发请求。

产品上不再让用户选「出口 / 中转」；但内部仍要区分一条节点是否健康，
以及国内机器该借道哪台海外节点。把这两个判断集中在这里，避免
admin.py、verify.py、UI 各写一套规则。
"""

import base64
import datetime
import time
import urllib.parse

try:
    from . import lifecycle
    from . import quota_guard
except ImportError:
    import lifecycle
    import quota_guard

# 这些状态表示节点有问题，不能进订阅。
# unknown 不在此列：外部节点永远未验证，但仍可被用户手动选择。
BAD_HEALTH = frozenset({"port", "tls", "proxy", "role_mismatch", "landing", "blocked", "timeout"})


def in_subscription(node, now_ts=None, usage_data=None):
    """节点是否应该出现在订阅里。统一遵循全生命周期状态机过滤：
    1. health 处于 BAD_HEALTH 异常状态 -> 排除
    2. enabled == False -> 排除
    3. 到期排空期 (draining, 距到期<=7天) -> 自动移出排空，避免黑洞
    4. 已过期 (expired) -> 排除
    5. 流量超过 85% 熔断安全水位 -> 自动移出订阅，杜绝产生超量扣费
    """
    if not lifecycle.is_in_subscription(node, now_ts=now_ts):
        return False
    if usage_data and quota_guard.is_node_circuit_broken(node.get("host"), usage_data):
        return False
    return True


def format_display_name(node, now_ts=None):
    """根据节点到期状态动态格式化客户端展示名称（订阅即通知中心）：
    - 距离到期 > 7 天或无到期时间：原名称，如 '硅谷主力出口'
    - 距离到期 1~7 天：带倒计时警示，如 '【剩3天到期】硅谷主力出口'
    - 距离到期 <= 1 天：带高危警示，如 '【⚠️明天到期!】硅谷主力出口'
    - 已过期：如被强制进订阅则显示 '【已过期】硅谷主力出口'
    """
    raw_name = node.get("name") or node.get("host") or "node"
    days_left = lifecycle.get_days_until_expiration(node, now_ts=now_ts)
    if days_left is None:
        return raw_name
    if days_left < 0:
        return f"【已过期】{raw_name}"
    if days_left <= 1:
        return f"【⚠️明天到期!】{raw_name}"
    if days_left <= 7:
        return f"【剩{days_left}天到期】{raw_name}"
    return raw_name


def vless_uri(n, now_ts=None):
    disp_name = format_display_name(n, now_ts=now_ts)
    q = ("encryption=none&flow=xtls-rprx-vision&security=reality"
         "&sni=%s&fp=chrome&pbk=%s&sid=%s&type=tcp&headerType=none"
         % (n.get("sni") or n["host"], n.get("pbk") or "", n.get("sid") or ""))
    return "vless://%s@%s:%s?%s#%s" % (n["uuid"], n["host"], n["port"], q,
                                      urllib.parse.quote(disp_name))


def hy2_uri(n, now_ts=None):
    disp_name = format_display_name(n, now_ts=now_ts)
    q = ("insecure=1&sni=%s&alpn=h3&obfs=salamander&obfs-password=%s"
         % (n.get("sni") or n["host"], n.get("obfs_password") or ""))
    return "hysteria2://%s@%s:%s?%s#%s" % (n["password"], n["host"], n["port"], q,
                                          urllib.parse.quote(disp_name))


def node_uri(n, now_ts=None):
    return hy2_uri(n, now_ts=now_ts) if n.get("type") == "hysteria2" else vless_uri(n, now_ts=now_ts)


def render_v2ray_base64(nodes, profile="all", now_ts=None, usage_data=None):
    """输出 Base64 订阅文本（Shadowrocket、v2rayN、Quantumult X 等）。"""
    valid = [n for n in (nodes or []) if in_subscription(n, now_ts=now_ts, usage_data=usage_data)]
    profile = (profile or "all").lower()
    if profile == "direct":
        # 纯直连省流模式：过滤所有国内中继节点，不消耗中继流量
        valid = [n for n in valid if (n.get("role") or "exit") != "relay" and (n.get("exit_country") or "").upper() != "CN"]
    elif profile == "office":
        # 客服办公模式：优先使用双落地高可用节点或中继
        office_valid = [n for n in valid if (n.get("role") or "") == "relay" or n.get("landing_policy") == "dual"]
        if office_valid:
            valid = office_valid

    lines = [node_uri(n, now_ts=now_ts) for n in valid]
    raw = "\n".join(lines)
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")


def clash_proxy_lines(n, now_ts=None):
    name = format_display_name(n, now_ts=now_ts)
    if n.get("type") == "hysteria2":
        return [
            '  - name: "%s"' % name,
            "    type: hysteria2",
            "    server: %s" % n["host"],
            "    port: %s" % n["port"],
            "    password: %s" % n["password"],
            "    sni: %s" % (n.get("sni") or n["host"]),
            "    skip-cert-verify: true",
            "    alpn: [h3]",
            "    obfs: salamander",
            "    obfs-password: %s" % (n.get("obfs_password") or ""),
        ]
    return [
        '  - name: "%s"' % name,
        "    type: vless",
        "    server: %s" % n["host"],
        "    port: %s" % n["port"],
        "    uuid: %s" % n["uuid"],
        "    network: tcp",
        "    udp: true",
        "    tls: true",
        "    flow: xtls-rprx-vision",
        "    servername: %s" % (n.get("sni") or n["host"]),
        "    client-fingerprint: chrome",
        "    reality-opts:",
        "      public-key: %s" % (n.get("pbk") or ""),
        "      short-id: %s" % (n.get("sid") or ""),
    ]


def render_clash_yaml(nodes, profile="all", now_ts=None, usage_data=None):
    """输出完整的 Clash / Mihomo / Clash Verge 订阅配置。支持分客群模式：
    - office: 客服防封号模式（强制锁定微信/国内直连白名单，走高可用双落地）
    - lite: 手机小白模式（单一「🚀 智能优选」单选组，无多余开关）
    - direct: 纯直连省流模式（彻底排除国内中继，0 中继双向流量消耗）
    - pro / all: 研发极客全能模式（多策略组自由切换，全节点暴露）
    """
    valid = [n for n in (nodes or []) if in_subscription(n, now_ts=now_ts, usage_data=usage_data)]
    profile = (profile or "all").lower()

    if profile == "direct":
        # 纯直连省流：剔除所有 relay 中继
        valid = [n for n in valid if (n.get("role") or "exit") != "relay" and (n.get("exit_country") or "").upper() != "CN"]

    names = [format_display_name(n, now_ts=now_ts) for n in valid]
    lines = [
        "# 由 admin.py 原生内置订阅生成（无需 subconverter 外部服务）",
        f"# 客群适配模式: {profile.upper()}",
        "mixed-port: 7890",
        "allow-lan: false",
        "mode: rule",
        "log-level: info",
        "ipv6: false",
        "",
        "dns:",
        "  enable: true",
        "  enhanced-mode: fake-ip",
        "  fake-ip-range: 198.18.0.1/16",
        "  nameserver:",
        "    - 223.5.5.5",
        "    - 119.29.29.29",
        "  fallback:",
        "    - https://1.1.1.1/dns-query",
        "    - https://8.8.8.8/dns-query",
        "",
        "proxies:",
    ]
    for n in valid:
        lines.extend(clash_proxy_lines(n, now_ts=now_ts))

    escaped_names = ", ".join('"%s"' % x for x in names)

    if profile == "office":
        lines.extend([
            "",
            "proxy-groups:",
            '  - name: "🛡️ 安全办公"',
            "    type: url-test",
            "    proxies: [" + escaped_names + "]",
            "    url: http://www.gstatic.com/generate_204",
            "    interval: 180",
            "",
            "rules:",
            "  - DOMAIN-KEYWORD,wechat,DIRECT",
            "  - DOMAIN-KEYWORD,weixin,DIRECT",
            "  - DOMAIN-KEYWORD,tencent,DIRECT",
            "  - DOMAIN-SUFFIX,qq.com,DIRECT",
            "  - DOMAIN-SUFFIX,alicdn.com,DIRECT",
            "  - DOMAIN-SUFFIX,taobao.com,DIRECT",
            "  - DOMAIN-SUFFIX,feishu.cn,DIRECT",
            "  - DOMAIN-SUFFIX,dingtalk.com,DIRECT",
            "  - DOMAIN-SUFFIX,alipay.com,DIRECT",
            "  - GEOIP,CN,DIRECT",
            '  - MATCH,"🛡️ 安全办公"',
            "",
        ])
    elif profile == "lite":
        lines.extend([
            "",
            "proxy-groups:",
            '  - name: "🚀 智能优选"',
            "    type: url-test",
            "    proxies: [" + escaped_names + "]",
            "    url: http://www.gstatic.com/generate_204",
            "    interval: 300",
            "",
            "rules:",
            "  - DOMAIN-KEYWORD,wechat,DIRECT",
            "  - DOMAIN-KEYWORD,weixin,DIRECT",
            "  - DOMAIN-KEYWORD,tencent,DIRECT",
            "  - DOMAIN-SUFFIX,qq.com,DIRECT",
            "  - DOMAIN-SUFFIX,alicdn.com,DIRECT",
            "  - DOMAIN-SUFFIX,taobao.com,DIRECT",
            "  - DOMAIN-SUFFIX,alipay.com,DIRECT",
            "  - GEOIP,CN,DIRECT",
            '  - MATCH,"🚀 智能优选"',
            "",
        ])
    else:  # pro / all / direct
        lines.extend([
            "",
            "proxy-groups:",
            '  - name: "自动选择"',
            "    type: url-test",
            "    proxies: [" + escaped_names + "]",
            "    url: http://www.gstatic.com/generate_204",
            "    interval: 300",
            "",
            '  - name: "节点选择"',
            "    type: select",
            '    proxies: ["自动选择", ' + escaped_names + "]",
            "",
            "rules:",
            "  - GEOIP,CN,DIRECT",
            "  - MATCH,节点选择",
            "",
        ])
    return "\n".join(lines)


def pick_landing(nodes, status=None):
    """从已有节点里挑一台最快的海外出口，供国内机器自动借道。

    只选：自建、health=ok、不是 relay、出口国家已知且不是 CN。
    返回 None 表示没有可用出口——调用方必须给出人话错误，不能继续装。
    """
    status = status or {}
    candidates = []
    for n in nodes or []:
        if n.get("health") != "ok":
            continue
        if n.get("source") == "external":
            continue
        if (n.get("role") or "exit") == "relay":
            continue
        country = (n.get("exit_country") or "").upper()
        if not country or country == "CN":
            continue
        if not all(n.get(k) for k in ("host", "port", "uuid", "pbk", "sid", "sni")):
            continue
        ms = (status.get(n.get("name")) or {}).get("ms") or 9999
        candidates.append((ms, n.get("name") or "", n))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    best = candidates[0][2]
    return {
        "host": best["host"],
        "port": best["port"],
        "uuid": best["uuid"],
        "pbk": best["pbk"],
        "sid": best["sid"],
        "sni": best["sni"],
    }
