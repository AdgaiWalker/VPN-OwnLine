"""决策提示：这条节点现在适合干什么。

纯函数：吃节点 + 探活 + 流量，吐一句话和一个依据。不读文件、不发请求。
"""

GOOD_AI = {"US", "SG", "JP", "KR", "TW", "HK"}

BAD_TEXT = {
    "port": "端口没放行",
    "tls": "服务没起来",
    "proxy": "机器活着但代理不通",
    "role_mismatch": "出去还是国内 IP，帮不上忙",
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


def _evaluate_action(node, status, iphealth, nodes):
    role = node.get("role") or "exit"
    source = node.get("source") or "builtin"
    country = (node.get("exit_country") or node.get("country") or "").upper()
    if source == "external" or role in ("relay", "standalone") or country == "CN":
        return None, ""
    if not status or status.get("ok") is False:
        return None, ""

    ms = status.get("ms")
    cn_ms = status.get("cn_ms")
    effective_ms = cn_ms if cn_ms is not None else ms
    cn_blocked = status.get("cn_ok") is False
    hy2_inactive = node.get("hy2_enabled") is False

    if hy2_inactive and (cn_blocked or (effective_ms is not None and effective_ms >= 220)):
        return "awaken_hy2", "检测到延迟偏高或直连受阻，建议开启 HY2 极速通道抗丢包"

    has_isp = bool(node.get("isp") or node.get("isp_proxy"))
    if not has_isp and isinstance(iphealth, dict) and (iphealth.get("hosting") or iphealth.get("proxy")):
        return "mount_isp", "当前出口为机房 IP，访问 ChatGPT/Claude 易风控，建议挂载静态住宅 IP"

    has_relay = any(
        isinstance(other, dict) and (other.get("role") == "relay" or (other.get("country") or "").upper() == "CN")
        for other in (nodes or ())
    )
    if not has_relay and (cn_blocked or (cn_ms is not None and cn_ms >= 220) or (ms is not None and ms >= 300)):
        return "add_relay", "直连延迟偏高，可接入国内中转专线降低晚高峰丢包"

    return None, ""


def advise(node, status=None, usage=None, iphealth=None, nodes=None):
    """返回 {"text": 一句话, "reason": 依据, "level": good|warn|bad, "action": ..., "action_hint": ...}"""
    health = node.get("health")
    source = node.get("source") or "builtin"
    ms = (status or {}).get("ms")
    country = node.get("exit_country") or ""
    parts = []

    def _pack(text, reason, level, *, allow_action=False):
        action, hint = _evaluate_action(node, status, iphealth, nodes) if allow_action else (None, "")
        return {"text": text, "reason": reason, "level": level, "action": action, "action_hint": hint}

    if health in BAD_TEXT:
        return _pack(BAD_TEXT[health], "自测：%s" % (node.get("health_detail") or health), "bad")

    if source == "external":
        return _pack("外部节点，未验证", "别人的机器，我们测不了它真通不通", "warn")

    if not status:
        return _pack("等待探测", "探活还没跑", "warn")

    if status.get("ok") is False:
        r = status.get("reason") or "port"
        label = BAD_TEXT.get(r, "服务不通")
        return _pack(label, "海外探活失败：%s" % label, "bad")

    if status.get("cn_ok") is False:
        r = status.get("cn_reason") or "port"
        label = BAD_TEXT.get(r, "连接异常")
        return _pack("国内连不上（可能被墙）", "海外在线，但国内探活失败：%s" % label, "bad", allow_action=True)

    if ms is not None:
        parts.append("延迟 %dms" % ms)
    if status.get("cn_ms") is not None:
        parts.append("国内 %dms" % status["cn_ms"])
    if country:
        parts.append("出口 %s" % country)
    u = _usage_text(usage)
    if u:
        parts.append(u)
    reason = " · ".join(parts)

    if usage and usage.get("total"):
        ratio = (usage.get("used") or 0) / usage["total"]
        if ratio >= 0.9:
            return _pack("流量快用完", reason, "warn")

    if ms is None:
        return _pack("日常可用", reason, "good", allow_action=True)

    if ms <= 300 and (country in GOOD_AI or not country):
        return _pack("AI 首选", reason, "good", allow_action=True)
    if ms <= 300:
        return _pack("日常可用", reason, "good", allow_action=True)
    if ms < 600:
        return _pack("日常可用，AI 偏慢", reason, "warn", allow_action=True)
    return _pack("能连，但慢", reason, "warn", allow_action=True)
