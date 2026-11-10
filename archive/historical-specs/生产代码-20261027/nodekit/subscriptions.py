"""订阅过滤与自动借道选择：纯函数，不读文件、不发请求。

产品上不再让用户选「出口 / 中转」；但内部仍要区分一条节点是否健康，
以及国内机器该借道哪台海外节点。把这两个判断集中在这里，避免
admin.py、verify.py、UI 各写一套规则。
"""

# 这些状态表示节点有问题，不能进订阅。
# unknown 不在此列：外部节点永远未验证，但仍可被用户手动选择。
BAD_HEALTH = frozenset({"port", "tls", "proxy", "role_mismatch", "landing", "blocked", "timeout"})


def in_subscription(node):
    """节点是否应该出现在订阅里。旧数据没有 health 字段时按可用处理。"""
    return (node or {}).get("health") not in BAD_HEALTH


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
