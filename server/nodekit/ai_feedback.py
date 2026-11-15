"""AI 反馈智能收集与聚类分析引擎 (AI Feedback Engine).

纯函数与确定性分析：
1. 聚合真实用户零门槛上报的现场黑匣子数据（日志切片、连通性探针、客户端平台）；
2. 自动聚类为四大典型情景（端口/防火墙阻断、晚高峰延迟丢包、客户端配置障碍、功能建议）；
3. 提取受影响节点与归因假设，输出结构化的排障建议与补丁方案。
100% 离线、零外部网络依赖、可被自动化门禁与 AI Agent 调用。
"""

import re
from typing import Any, Dict, List, Optional


CATEGORIES = {
    "port_or_firewall": {
        "name": "端口与防火墙阻断",
        "keywords": ["连不上", "端口", "阻断", "防火墙", "超时", "timeout", "refused", "port blocked", "死活连不上"],
        "default_fix": "检查对应服务器安全组与云控制台防火墙是否放行目标端口（如 443/8443）；若为新节点，触发一键自愈修复残留进程占用。",
    },
    "latency_or_congestion": {
        "name": "晚高峰延迟与卡顿",
        "keywords": ["卡", "慢", "卡顿", "视频", "油管", "youtube", "转圈", "丢包", "buffer", "lag", "latency"],
        "default_fix": "建议开启该节点的 HY2 极速通道（QUIC 单包重传抵抗丢包），或将国内中转专线与落地解耦重新绑定低延迟机房。",
    },
    "client_config": {
        "name": "客户端配置与导入障碍",
        "keywords": ["小火箭", "shadowrocket", "clash", "导入", "订阅", "更新", "扫码", "二维码", "无法使用", "规则"],
        "default_fix": "检查客户端是否开启 UDP 转发与系统代理权限；引导用户重新复制最新 Clash 订阅链接或使用小火箭专用二维码。",
    },
    "feature_idea": {
        "name": "新功能与体验建议",
        "keywords": ["建议", "想要", "希望", "新功能", "支持", "增加", "能不能", "feature", "idea"],
        "default_fix": "评估用户场景通用性，若符合自建专属高可用定位，纳入版本演进待办。",
    },
    "general": {
        "name": "常规故障求助",
        "keywords": [],
        "default_fix": "结合用户现场环境指纹与节点探活切片排查当前出海出口状态。",
    },
}


def categorize_entry(entry: Dict[str, Any]) -> str:
    """根据反馈文本与现场诊断切片确定问题归类。"""
    msg = (entry.get("message") or "").lower()
    intent = entry.get("type") or "bug"
    diag = entry.get("diagnostics") or {}

    # 1. 显式意图判断
    if intent == "idea":
        return "feature_idea"

    # 2. 现场诊断客观证据分析 (优先于用户非专业文本)
    nodes = diag.get("nodes") or []
    has_port_failure = False
    has_latency_failure = False
    for n in nodes:
        health = str(n.get("health") or "")
        ok = n.get("ok")
        cn_ok = n.get("cn_ok")
        ms = n.get("ms") or 0
        cn_ms = n.get("cn_ms") or 0

        if health == "port" or ok is False or cn_ok is False:
            has_port_failure = True
        if (ms and ms > 250) or (cn_ms and cn_ms > 250):
            has_latency_failure = True

    if has_port_failure:
        return "port_or_firewall"

    # 3. 关键字语义匹配
    for cat_key, meta in CATEGORIES.items():
        if cat_key in ("general", "feature_idea"):
            continue
        for kw in meta["keywords"]:
            if kw in msg:
                return cat_key

    if has_latency_failure:
        return "latency_or_congestion"

    if any(kw in msg for kw in CATEGORIES["feature_idea"]["keywords"]):
        return "feature_idea"

    return "general"


def analyze_feedback_entries(entries: List[Dict[str, Any]], active_nodes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """对用户反馈历史进行 AI 智能聚类分析与行动建议生成。"""
    if not entries:
        return {
            "ok": True,
            "total_count": 0,
            "urgency": "clean",
            "summary": "当前暂无用户反馈上报，所有服务与节点状态稳定。",
            "clusters": [],
            "action_items": [],
        }

    grouped: Dict[str, List[Dict[str, Any]]] = {k: [] for k in CATEGORIES}
    affected_nodes_map: Dict[str, set] = {k: set() for k in CATEGORIES}

    for entry in entries:
        cat = categorize_entry(entry)
        grouped[cat].append(entry)

        # 收集受影响节点
        diag = entry.get("diagnostics") or {}
        for n in (diag.get("nodes") or []):
            name = n.get("name")
            if name:
                health = str(n.get("health") or "")
                ok = n.get("ok")
                if health != "ok" or ok is False:
                    affected_nodes_map[cat].add(name)

    clusters = []
    action_items = []
    has_blocking_issue = False

    for cat_key, items in grouped.items():
        if not items:
            continue
        meta = CATEGORIES[cat_key]
        affected_nodes = sorted(list(affected_nodes_map[cat_key]))
        count = len(items)

        # 典型用户原声采样
        sample_quotes = []
        for it in items[:3]:
            m = (it.get("message") or "").strip()
            if m and m not in sample_quotes:
                sample_quotes.append(m[:60])

        cluster = {
            "key": cat_key,
            "name": meta["name"],
            "count": count,
            "affected_nodes": affected_nodes,
            "sample_quotes": sample_quotes,
            "proposed_fix": meta["default_fix"],
        }
        clusters.append(cluster)

        if cat_key == "port_or_firewall":
            has_blocking_issue = True
            action_items.append("【高优先级】检测到节点阻断反馈，请确认云控制台防火墙端口（或执行一键自愈）。")
        elif cat_key == "latency_or_congestion":
            action_items.append("【性能优化】用户反馈高峰卡顿，建议检查并启用对应节点的 HY2 极速通道。")
        elif cat_key == "client_config":
            action_items.append("【体验支持】存在客户端配置问题，建议核对订阅链接连通性并在指引中提示 UDP 放行。")

    urgency = "high" if has_blocking_issue else ("medium" if clusters else "low")

    # 生成高层次总结
    top_cluster = max(clusters, key=lambda x: x["count"]) if clusters else None
    top_symptom = top_cluster["name"] if top_cluster else "无明显异常"
    summary = f"共收集 {len(entries)} 条用户现场反馈。主要集中于「{top_symptom}」（共 {top_cluster['count'] if top_cluster else 0} 次上报）。"

    return {
        "ok": True,
        "total_count": len(entries),
        "urgency": urgency,
        "summary": summary,
        "clusters": clusters,
        "action_items": action_items,
    }
