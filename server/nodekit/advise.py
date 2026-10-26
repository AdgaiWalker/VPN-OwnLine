"""决策提示：这条节点现在适合干什么。

纯函数：吃节点 + 探活 + 流量，吐一句话和一个依据。不读文件、不发请求。
"""

GOOD_AI = {"US", "SG", "JP", "KR", "TW", "HK"}

BAD_TEXT = {
    "port": "端口没放行",
    "tls": "服务没起来",
    "role_mismatch": "出口在国内，翻不了墙",
    "landing": "连不上落地",
    "blocked": "可能被墙了",
    "timeout": "安装超时",
}


def _usage_text(usage):
    if not usage:
        return ""
    used = usage.get("used") or 0
    total = usage.get("total") or 0
    if not total:
        return ""
    return "本月 %.1f/%.0f GB" % (used, total)


def advise(node, status=None, usage=None):
    """返回 {"text": 一句话, "reason": 依据, "level": good|warn|bad}"""
    health = node.get("health")
    role = node.get("role") or "exit"
    source = node.get("source") or "builtin"
    ms = (status or {}).get("ms")
    country = node.get("exit_country") or ""
    parts = []

    if health in BAD_TEXT:
        return {"text": BAD_TEXT[health], "reason": "自测：%s" % (node.get("health_detail") or health), "level": "bad"}

    if role == "relay":
        parts.append("中转，不直接给客户端用")
        if node.get("landing", {}).get("host"):
            parts.append("落地 %s" % node["landing"]["host"])
        return {"text": "中转跳板", "reason": " · ".join(parts), "level": "good"}

    if source == "external":
        return {"text": "外部节点，未验证", "reason": "别人的机器，我们测不了它真通不通", "level": "warn"}

    if not status:
        return {"text": "等待探测", "reason": "探活还没跑", "level": "warn"}

    if ms is not None:
        parts.append("延迟 %dms" % ms)
    if country:
        parts.append("出口 %s" % country)
    u = _usage_text(usage)
    if u:
        parts.append(u)
    reason = " · ".join(parts)

    if usage and usage.get("total"):
        ratio = (usage.get("used") or 0) / usage["total"]
        if ratio >= 0.9:
            return {"text": "流量快用完", "reason": reason, "level": "warn"}

    if ms is None:
        return {"text": "日常可用", "reason": reason, "level": "good"}

    if ms <= 300 and (country in GOOD_AI or not country):
        return {"text": "AI 首选", "reason": reason, "level": "good"}
    if ms <= 300:
        return {"text": "日常可用", "reason": reason, "level": "good"}
    if ms < 600:
        return {"text": "日常可用，AI 偏慢", "reason": reason, "level": "warn"}
    return {"text": "能连，但慢", "reason": reason, "level": "warn"}
