"""订阅过滤与自动借道选择：纯函数，不读文件、不发请求。

产品上不再让用户选「出口 / 中转」；但内部仍要区分一条节点是否健康，
以及国内机器该借道哪台海外节点。把这两个判断集中在这里，避免
admin.py、verify.py、UI 各写一套规则。
"""

import base64
import datetime
import json
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from . import lifecycle
    from . import quota_guard
except ImportError:
    import lifecycle
    import quota_guard

# 这些状态表示节点有问题，不能进订阅。
# unknown 不在此列：外部节点永远未验证，但仍可被用户手动选择。
BAD_HEALTH = frozenset({"port", "tls", "proxy", "role_mismatch", "landing", "blocked", "timeout"})


class SubscriptionUserInfo:
    """标准 Subscription-Userinfo 响应头值对象。

    格式：upload=0; download=<used_bytes>; total=<total_bytes>; expire=<earliest_expire_epoch>
    """

    def __init__(
        self,
        upload: int = 0,
        download: int = 0,
        total: int = 0,
        expire: Optional[int] = None,
    ) -> None:
        self.upload = max(0, int(upload))
        self.download = max(0, int(download))
        self.total = max(0, int(total))
        self.expire = int(expire) if expire is not None else None

    def format(self) -> str:
        parts = [f"upload={self.upload}", f"download={self.download}", f"total={self.total}"]
        if self.expire:
            parts.append(f"expire={self.expire}")
        return "; ".join(parts)

    @classmethod
    def parse(cls, header_value: str) -> Optional["SubscriptionUserInfo"]:
        if not header_value or not isinstance(header_value, str):
            return None
        parts = {}
        for item in header_value.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                parts[k.strip().lower()] = v.strip()
        if not any(k in parts for k in ("upload", "download", "total")):
            return None
        try:
            exp_val = parts.get("expire")
            exp_ts = int(exp_val) if exp_val and exp_val.isdigit() else None
            return cls(
                upload=int(parts.get("upload", 0)),
                download=int(parts.get("download", 0)),
                total=int(parts.get("total", 0)),
                expire=exp_ts,
            )
        except Exception:
            return None


def in_subscription(node, now_ts=None, usage_data=None, controllable_hosts=None):
    """节点是否应该出现在订阅里。统一遵循全生命周期状态机过滤：
    1. health 处于 BAD_HEALTH 异常状态 -> 排除
    2. enabled == False -> 排除
    3. 到期排空期 (draining, 距到期<=7天) -> 自动移出排空，避免黑洞
    4. 已过期 (expired) -> 排除
    5. 已暂停，或受控节点达到所设流量阈值 -> 从订阅移除；不保证避免超额费用
    """
    if not lifecycle.is_in_subscription(node, now_ts=now_ts):
        return False
    host = node.get("host")
    controllable = (host in controllable_hosts if controllable_hosts is not None
                    else quota_guard.supports_quota_control(node))
    if (host in quota_guard.stopped_hosts() or
            (controllable and usage_data and
             quota_guard.is_node_circuit_broken(node.get("host"), usage_data))):
        return False
    return True


def subscription_userinfo(usage_data, nodes=None):
    """生成适用于 Shadowrocket / Clash / Stash / Surge 的标准 Subscription-Userinfo 响应头。
    格式：upload=0; download=<used_bytes>; total=<total_bytes>; expire=<earliest_expire_epoch>
    仅统计境外真实出海出口节点（硅谷、新加坡等），国内中转跳板/国内独立机不重复计入出海总配额。
    """
    if not isinstance(usage_data, dict):
        return None

    exit_keys = set()
    if nodes:
        for n in nodes:
            raw_name = n.get("name") or ""
            host = n.get("host") or n.get("ip") or ""
            # 过滤国内中转机与国内独立机，仅聚合真实境外出口配额
            if (
                n.get("role") in ("relay", "standalone")
                or n.get("region_type") == "cn"
                or (n.get("exit_country") or "").upper() == "CN"
                or raw_name in ("北京", "广州", "上海", "深圳", "南京", "成都")
            ):
                continue
            if n.get("role") == "exit" or (n.get("exit_country") and n.get("exit_country") != "CN"):
                if host:
                    exit_keys.add(host)
                if n.get("ip"):
                    exit_keys.add(n["ip"])
                if raw_name:
                    exit_keys.add(raw_name)

    used_gb = 0.0
    total_gb = 0.0
    earliest_ts = None
    for k, v in usage_data.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        if exit_keys and (k not in exit_keys):
            continue
        try:
            u = float(v.get("used", 0) or 0)
            t = float(v.get("total", 0) or 0)
            used_gb += u
            total_gb += t
            exp_str = v.get("expire") or v.get("end")
            if exp_str:
                exp_ts = _parse_date_epoch(exp_str)
                if exp_ts and (earliest_ts is None or exp_ts < earliest_ts):
                    earliest_ts = exp_ts
        except Exception:
            continue
    if total_gb <= 0:
        return None
    download_bytes = int(used_gb * 1024 * 1024 * 1024)
    total_bytes = int(total_gb * 1024 * 1024 * 1024)
    info = SubscriptionUserInfo(
        upload=0,
        download=download_bytes,
        total=total_bytes,
        expire=earliest_ts,
    )
    return info.format()


def _parse_date_epoch(val):
    if not val:
        return None
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        val = val.strip()
        try:
            return int(float(val))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.datetime.strptime(val, fmt).replace(tzinfo=datetime.timezone.utc)
                return int(dt.timestamp())
            except ValueError:
                continue
    return None


def _friendly_dest_label(node):
    landing = node.get("landing") or {}
    lname = str(landing.get("name") or "").strip()
    cc = str(node.get("exit_country") or landing.get("country") or "").upper()
    if "新加坡" in lname or cc == "SG":
        return "🇸🇬 新加坡"
    if "东京" in lname or "日本" in lname or cc == "JP":
        return "🇯🇵 日本"
    if "香港" in lname or cc == "HK":
        return "🇭🇰 香港"
    if "硅谷" in lname or "美" in lname or cc == "US":
        return "🇺🇸 硅谷"
    if lname:
        return lname
    return "🇺🇸 硅谷"


def friendly_base_name(node):
    """把内部简写节点名转换为用户可读的「人话专线/直连名称」（纯字段驱动，零硬编码 IP）"""
    if not isinstance(node, dict):
        return str(node or "")
    if node.get("display_name"):
        return str(node["display_name"])
    raw_name = node.get("name") or node.get("host") or "node"
    # 如果已经含有人话专线或直连标记，原样保留
    if "➔" in raw_name or "专线" in raw_name or "直连" in raw_name:
        return raw_name
    role = node.get("role") or ""
    is_hy2 = (node.get("type") == "hysteria2" or "hy2" in raw_name.lower())

    if role == "standalone" or (role != "relay" and not node.get("landing") and raw_name in ("北京", "广州", "上海", "深圳")):
        return f"🇨🇳 {raw_name} (国内独立服务器)"

    if raw_name == "北京":
        dest = _friendly_dest_label(node)
        return f"🇨🇳 北京专线 ➔ {dest} (极速防卡顿)"
    if raw_name == "广州":
        dest = _friendly_dest_label(node)
        return f"🇨🇳 广州专线 ➔ {dest} (备用专线)"
    if raw_name in ("硅谷-HY2", "硅谷_HY2"):
        return "🇺🇸 硅谷-HY2 (HY2 极速)"
    if raw_name == "硅谷":
        return "🇺🇸 硅谷直连 (HY2 极速)" if is_hy2 else "🇺🇸 硅谷直连 (Reality 稳定)"
    if raw_name == "新加坡":
        return "🇸🇬 新加坡直连 (备用出海)"

    if role == "relay":
        dest = _friendly_dest_label(node) if (node.get("landing") or node.get("exit_country")) else "落地出口"
        return f"🇨🇳 {raw_name}专线 ➔ {dest}"
    return raw_name


def format_display_name(node, now_ts=None):
    """根据节点到期状态动态格式化客户端展示名称（订阅即通知中心）：
    - 距离到期 > 7 天或无到期时间：人话展示名称，如 '🇺🇸 硅谷直连 (Reality 稳定)'
    - 距离到期 1~7 天：带倒计时警示，如 '【剩3天到期】🇺🇸 硅谷直连 (Reality 稳定)'
    - 距离到期 <= 1 天：带高危警示，如 '【⚠️明天到期!】🇺🇸 硅谷直连 (Reality 稳定)'
    - 已过期：如被强制进订阅则显示 '【已过期】...'
    """
    base_name = friendly_base_name(node)
    days_left = lifecycle.get_days_until_expiration(node, now_ts=now_ts)
    if days_left is None:
        return base_name
    if days_left < 0:
        return f"【已过期】{base_name}"
    if days_left <= 1:
        return f"【⚠️明天到期!】{base_name}"
    if days_left <= 7:
        return f"【剩{days_left}天到期】{base_name}"
    return base_name


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
    eligible = quota_guard.controllable_hosts(nodes)
    valid = [n for n in (nodes or []) if in_subscription(n, now_ts=now_ts, usage_data=usage_data, controllable_hosts=eligible)]
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
    eligible = quota_guard.controllable_hosts(nodes)
    valid = [n for n in (nodes or []) if in_subscription(n, now_ts=now_ts, usage_data=usage_data, controllable_hosts=eligible)]
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
        # 挑选适合 AI 业务的首选节点（挂载了住宅代理优先，其次美区/硅谷出口，保底全节点）
        ai_candidates = []
        for n in valid:
            if n.get("isp"):
                ai_candidates.append(format_display_name(n, now_ts=now_ts))
        if not ai_candidates:
            for n in valid:
                c = (n.get("exit_country") or "").upper()
                nm = n.get("name") or ""
                if c == "US" or "硅谷" in nm or "美" in nm:
                    ai_candidates.append(format_display_name(n, now_ts=now_ts))
        if not ai_candidates:
            ai_candidates = list(names)

        # 构造不重复的代理列表
        ai_proxies = []
        for x in ai_candidates:
            if x not in ai_proxies:
                ai_proxies.append(x)
        if "自动选择" not in ai_proxies:
            ai_proxies.append("自动选择")
        for x in names:
            if x not in ai_proxies:
                ai_proxies.append(x)
        escaped_ai = ", ".join('"%s"' % x for x in ai_proxies)

        node_select_proxies = ['"自动选择"', '"🤖 AI 业务"'] + ['"%s"' % x for x in names if x not in ("自动选择", "🤖 AI 业务")]
        escaped_node_select = ", ".join(node_select_proxies)

        lines.extend([
            "",
            "proxy-groups:",
            '  - name: "自动选择"',
            "    type: url-test",
            "    proxies: [" + escaped_names + "]",
            "    url: http://www.gstatic.com/generate_204",
            "    interval: 300",
            "",
            '  - name: "🤖 AI 业务"',
            "    type: select",
            "    proxies: [" + escaped_ai + "]",
            "",
            '  - name: "节点选择"',
            "    type: select",
            "    proxies: [" + escaped_node_select + "]",
            "",
            "rules:",
            "  - DOMAIN-KEYWORD,openai,🤖 AI 业务",
            "  - DOMAIN-KEYWORD,anthropic,🤖 AI 业务",
            "  - DOMAIN-KEYWORD,claude,🤖 AI 业务",
            "  - DOMAIN-SUFFIX,oaistatic.com,🤖 AI 业务",
            "  - DOMAIN-SUFFIX,oaiusercontent.com,🤖 AI 业务",
            "  - DOMAIN-SUFFIX,ai.google.dev,🤖 AI 业务",
            "  - DOMAIN-SUFFIX,bard.google.com,🤖 AI 业务",
            "  - DOMAIN-KEYWORD,wechat,DIRECT",
            "  - DOMAIN-KEYWORD,weixin,DIRECT",
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
