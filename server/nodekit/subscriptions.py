"""订阅过滤与自动借道选择：纯函数，不读文件、不发请求。

产品上不再让用户选「出口 / 中转」；但内部仍要区分一条节点是否健康，
以及国内机器该借道哪台海外节点。把这两个判断集中在这里，避免
admin.py、verify.py、UI 各写一套规则。
"""

import base64
import urllib.parse

# 这些状态表示节点有问题，不能进订阅。
# unknown 不在此列：外部节点永远未验证，但仍可被用户手动选择。
BAD_HEALTH = frozenset({"port", "tls", "proxy", "role_mismatch", "landing", "blocked", "timeout"})


def in_subscription(node):
    """节点是否应该出现在订阅里。旧数据没有 health 字段时按可用处理。"""
    return (node or {}).get("health") not in BAD_HEALTH


def vless_uri(n):
    q = ("encryption=none&flow=xtls-rprx-vision&security=reality"
         "&sni=%s&fp=chrome&pbk=%s&sid=%s&type=tcp&headerType=none"
         % (n.get("sni") or n["host"], n.get("pbk") or "", n.get("sid") or ""))
    return "vless://%s@%s:%s?%s#%s" % (n["uuid"], n["host"], n["port"], q,
                                      urllib.parse.quote(n.get("name") or "node"))


def hy2_uri(n):
    q = ("insecure=1&sni=%s&alpn=h3&obfs=salamander&obfs-password=%s"
         % (n.get("sni") or n["host"], n.get("obfs_password") or ""))
    return "hysteria2://%s@%s:%s?%s#%s" % (n["password"], n["host"], n["port"], q,
                                          urllib.parse.quote(n.get("name") or "node"))


def node_uri(n):
    return hy2_uri(n) if n.get("type") == "hysteria2" else vless_uri(n)


def render_v2ray_base64(nodes):
    """输出 Base64 订阅文本（Shadowrocket、v2rayN、Quantumult X 等）。"""
    valid = [n for n in (nodes or []) if in_subscription(n)]
    lines = [node_uri(n) for n in valid]
    raw = "\n".join(lines)
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")


def clash_proxy_lines(n):
    name = n.get("name") or n["host"]
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


def render_clash_yaml(nodes):
    """输出完整的 Clash / Mihomo / Clash Verge 订阅配置。"""
    valid = [n for n in (nodes or []) if in_subscription(n)]
    names = [n.get("name") or n["host"] for n in valid]
    lines = [
        "# 由 admin.py 原生内置订阅生成（无需 subconverter 外部服务）",
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
        lines.extend(clash_proxy_lines(n))

    escaped_names = ", ".join('"%s"' % x for x in names)
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
