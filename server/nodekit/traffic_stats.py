#!/usr/bin/env python3
"""traffic_stats.py: 多维度流量时序聚合器与智能使用额度规划引擎（纯函数、零外部依赖）。

职责：
1. 消费 vnStat JSON 或定期快照采样，聚合出日消耗、周消耗、月消耗、年消耗；
2. 结合腾讯云账单周期（如 10-23 至 11-23），智能推算"剩余天数"、"剩余可用额度"与"每日建议安全配额"；
3. 输出面向普通用户的行动建议（回答："今天用了多少？之后我该怎么用？"）。
"""
import datetime
import json
import math
import os
from typing import Any, Dict, List, Optional

try:
    from .store import AtomicJsonStore
except ImportError:
    from store import AtomicJsonStore

CN_TZ = datetime.timezone(datetime.timedelta(hours=8))


def _safe_nonneg_float(val: Any, default: Optional[float] = 0.0) -> Optional[float]:
    if isinstance(val, bool) or val is None:
        return default
    try:
        num = float(val)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(num):
        return default
    return max(0.0, num)


def parse_vnstat_json(data: Any) -> Dict[str, Any]:
    """解析 vnStat --json 输出格式（兼容 vnStat 2.x 结构）。
    
    返回标准字段:
      - today_bytes
      - yesterday_bytes
      - this_week_bytes
      - this_month_bytes
      - this_year_bytes
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            return {}
    if not isinstance(data, dict):
        return {}

    interfaces = data.get("interfaces", [])
    if not interfaces or not isinstance(interfaces, list):
        return {}

    iface = interfaces[0]
    traffic = iface.get("traffic", {}) if isinstance(iface, dict) else {}

    days = traffic.get("day", []) or traffic.get("days", [])
    months = traffic.get("month", []) or traffic.get("months", [])
    years = traffic.get("year", []) or traffic.get("years", [])

    today_bytes = 0
    yesterday_bytes = 0
    this_week_bytes = 0
    this_month_bytes = 0
    this_year_bytes = 0

    # 提取日数据（通常以当天为 days[0] 或按日期倒序）
    if days and isinstance(days, list):
        # 兼容最新在前面或在后面的情况，按 date 比较
        def _day_key(d):
            dt = d.get("date", {})
            return (dt.get("year", 0), dt.get("month", 0), dt.get("day", 0))

        sorted_days = sorted(days, key=_day_key, reverse=True)
        if len(sorted_days) >= 1:
            d0 = sorted_days[0]
            today_bytes = (d0.get("rx", 0) + d0.get("tx", 0)) * 1024  # vnStat 默认单位为 KiB
        if len(sorted_days) >= 2:
            d1 = sorted_days[1]
            yesterday_bytes = (d1.get("rx", 0) + d1.get("tx", 0)) * 1024
        # 统计过去 7 天
        for d in sorted_days[:7]:
            this_week_bytes += (d.get("rx", 0) + d.get("tx", 0)) * 1024

    if months and isinstance(months, list):
        def _month_key(m):
            dt = m.get("date", {})
            return (dt.get("year", 0), dt.get("month", 0))

        sorted_months = sorted(months, key=_month_key, reverse=True)
        if sorted_months:
            m0 = sorted_months[0]
            this_month_bytes = (m0.get("rx", 0) + m0.get("tx", 0)) * 1024

    if years and isinstance(years, list):
        def _year_key(y):
            dt = y.get("date", {})
            return dt.get("year", 0)

        sorted_years = sorted(years, key=_year_key, reverse=True)
        if sorted_years:
            y0 = sorted_years[0]
            this_year_bytes = (y0.get("rx", 0) + y0.get("tx", 0)) * 1024

    return {
        "today_gb": round(today_bytes / (1024 ** 3), 2),
        "yesterday_gb": round(yesterday_bytes / (1024 ** 3), 2),
        "this_week_gb": round(this_week_bytes / (1024 ** 3), 2),
        "this_month_gb": round(this_month_bytes / (1024 ** 3), 2),
        "this_year_gb": round(this_year_bytes / (1024 ** 3), 2),
    }


def record_history_snapshot(history: Dict[str, Any], usage_item: Dict[str, Any],
                            host: str, now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """将一次采样点记入历史时序库，处理跨天、月账单清零重置，并计算增量。"""
    if now is None:
        now = datetime.datetime.now(CN_TZ)

    today_str = now.strftime("%Y-%m-%d")
    current_used = _safe_nonneg_float(usage_item.get("used"), 0.0)
    current_total = _safe_nonneg_float(usage_item.get("total"), 0.0)

    nodes = history.setdefault("nodes", {})
    node_data = nodes.setdefault(host, {
        "last_seen_used": current_used,
        "daily_totals": {},
        "snapshots": [],
        "last_date": today_str,
    })

    last_seen = _safe_nonneg_float(node_data.get("last_seen_used"), default=None)
    last_date = node_data.get("last_date", today_str)
    daily_totals = node_data.setdefault("daily_totals", {})

    if last_seen is None:
        # 首次初始化
        delta = 0.0
    elif current_used >= last_seen:
        # 正常递增
        delta = current_used - last_seen
    else:
        # 云厂商计费周期发生重置（月清零），新周期使用量即为增量
        delta = current_used

    # 累加到今日消耗
    prev_today = _safe_nonneg_float(daily_totals.get(today_str), 0.0)
    daily_totals[today_str] = round(prev_today + delta, 3)

    node_data["last_seen_used"] = current_used
    node_data["last_date"] = today_str

    # 记录采样点（保留最近 48 小时采样，防止文件膨胀）
    snapshots = node_data.setdefault("snapshots", [])
    snapshots.append({
        "ts": int(now.timestamp()),
        "iso": now.isoformat(),
        "used": current_used,
        "total": current_total,
    })
    # 裁剪超过 48 小时（288 个点）的细粒度快照
    if len(snapshots) > 288:
        node_data["snapshots"] = snapshots[-288:]

    # 裁剪超过 90 天的日统计
    sorted_days = sorted(daily_totals.keys())
    if len(sorted_days) > 90:
        for old_d in sorted_days[:-90]:
            daily_totals.pop(old_d, None)

    history["updated_at"] = now.isoformat()
    return history


def generate_usage_guidance(used_gb: float, total_gb: float,
                            start_str: str, end_str: str,
                            today_used_gb: float,
                            now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """核心算法：计算剩余天数、日均预算与针对用户的行动指南。"""
    if now is None:
        now = datetime.datetime.now(CN_TZ)

    used_gb = _safe_nonneg_float(used_gb, 0.0)
    total_gb = _safe_nonneg_float(total_gb, 0.0)
    today_used_gb = _safe_nonneg_float(today_used_gb, 0.0)

    today_date = now.date()

    # 计算剩余天数
    days_remaining = 30
    if end_str:
        try:
            end_date = datetime.date.fromisoformat(end_str[:10])
            delta_days = (end_date - today_date).days
            days_remaining = max(1, delta_days)
        except Exception:
            days_remaining = 30

    remaining_gb = max(0.0, round(total_gb - used_gb, 2)) if total_gb > 0 else 0.0
    daily_budget_gb = round(remaining_gb / days_remaining, 2) if days_remaining > 0 and remaining_gb > 0 else 0.0

    # 评估当前节奏与状态
    ratio = (today_used_gb / daily_budget_gb) if daily_budget_gb > 0 else 0.0

    if total_gb > 0 and (used_gb / total_gb) >= 0.90:
        pace = "critical"
        badge = "紧急预警"
        advice_text = f"月度流量仅剩 {remaining_gb} GB（已用 {round(used_gb/total_gb*100, 1)}%），请注意控制大流量消耗或调高保护阈值。"
    elif daily_budget_gb > 0 and ratio > 1.2:
        pace = "heavy"
        badge = "今日消耗偏快"
        advice_text = f"今日已用 {today_used_gb} GB，略超出建议日均配额（{daily_budget_gb} GB/天），建议留意视频画质或后台下载。"
    elif daily_budget_gb > 0 and ratio < 0.5:
        pace = "abundant"
        badge = "余量极其充裕"
        if days_remaining <= 2:
            advice_text = f"离重置还有 {days_remaining} 天，剩余 {remaining_gb} GB。日均可用 {daily_budget_gb} GB/天，账单周期即将切换，建议保留安全余量避免超量计费。"
        else:
            advice_text = f"离重置还有 {days_remaining} 天，剩余 {remaining_gb} GB。日均可用 {daily_budget_gb} GB/天，可随心看高清/测速。"
    else:
        pace = "normal"
        badge = "用量健康稳定"
        advice_text = f"离重置还有 {days_remaining} 天，日均建议配额 {daily_budget_gb} GB/天，使用节奏良好。"

    return {
        "days_remaining": days_remaining,
        "remaining_gb": remaining_gb,
        "daily_budget_gb": daily_budget_gb,
        "today_used_gb": today_used_gb,
        "pacing_ratio": round(ratio, 2),
        "pace": pace,
        "badge": badge,
        "text": advice_text,
    }


def compute_node_stats(host: str, usage_item: Dict[str, Any],
                       history: Dict[str, Any],
                       vnstat_raw: Optional[Any] = None,
                       now: Optional[datetime.datetime] = None) -> Dict[str, Any]:
    """汇总单个节点的日/周/月/年消耗指标与规划建议。"""
    if now is None:
        now = datetime.datetime.now(CN_TZ)

    today_str = now.strftime("%Y-%m-%d")
    current_used = _safe_nonneg_float(usage_item.get("used"), 0.0)
    current_total = _safe_nonneg_float(usage_item.get("total"), 0.0)
    start_str = usage_item.get("start", "")
    end_str = usage_item.get("end", "")

    # 优先解析 vnStat 原生数据
    vn_stats = parse_vnstat_json(vnstat_raw) if vnstat_raw else {}

    # 从采样时序提取
    node_history = history.get("nodes", {}).get(host, {})
    daily_totals = node_history.get("daily_totals", {})

    hist_today = round(daily_totals.get(today_str, 0.0), 2)

    # 昨天
    yesterday_date = now - datetime.timedelta(days=1)
    yesterday_str = yesterday_date.strftime("%Y-%m-%d")
    hist_yesterday = round(daily_totals.get(yesterday_str, 0.0), 2)

    # 本周（过去 7 天）
    week_sum = 0.0
    for i in range(7):
        d_str = (now - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        week_sum += daily_totals.get(d_str, 0.0)
    hist_week = round(week_sum, 2)

    # 年累计（当年所有已记录日期）
    year_prefix = now.strftime("%Y-")
    year_sum = sum(v for k, v in daily_totals.items() if k.startswith(year_prefix))
    # 结合当前账单月累计与历史跨月
    hist_year = round(max(year_sum, current_used), 2)

    today_gb = vn_stats.get("today_gb") if (vn_stats.get("today_gb") is not None and vn_stats.get("today_gb") > 0) else hist_today
    yesterday_gb = vn_stats.get("yesterday_gb") if vn_stats.get("yesterday_gb") is not None else hist_yesterday
    week_gb = vn_stats.get("this_week_gb") if vn_stats.get("this_week_gb") is not None else hist_week
    month_gb = current_used
    year_gb = vn_stats.get("this_year_gb") if vn_stats.get("this_year_gb") is not None else hist_year

    guidance = generate_usage_guidance(
        used_gb=current_used,
        total_gb=current_total,
        start_str=start_str,
        end_str=end_str,
        today_used_gb=today_gb,
        now=now,
    )

    return {
        "host": host,
        "region": usage_item.get("region", ""),
        "used_gb": current_used,
        "total_gb": current_total,
        "start": start_str,
        "end": end_str,
        "today_gb": today_gb,
        "yesterday_gb": yesterday_gb,
        "this_week_gb": week_gb,
        "this_month_gb": month_gb,
        "this_year_gb": year_gb,
        "guidance": guidance,
    }


def aggregate_all_traffic_stats(usage_dict: Dict[str, Any],
                                history: Dict[str, Any],
                                now: Optional[datetime.datetime] = None,
                                active_nodes: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """全系统多节点流量透视聚合报表。

    支持根据 active_nodes 过滤废弃或非活跃云实例，仅将出海落地主力节点纳管入配额基准，
    保证控制台顶部进度条与行动指引单一真理源（SSOT）一致。
    """
    if now is None:
        now = datetime.datetime.now(CN_TZ)

    active_hosts = set()
    egress_hosts = set()
    if active_nodes is not None:
        for n in active_nodes:
            h = n.get("host") or n.get("ip")
            if h:
                active_hosts.add(h)
                if n.get("role") not in ("relay", "standalone"):
                    egress_hosts.add(h)

    use_filter = bool(active_hosts)
    if not egress_hosts:
        egress_hosts = set(active_hosts)

    nodes_stats = {}
    tot_today = 0.0
    tot_yesterday = 0.0
    tot_week = 0.0
    tot_month = 0.0
    tot_year = 0.0
    tot_total = 0.0

    primary_guidance = None
    primary_candidate = None

    for k, v in usage_dict.items():
        if k.startswith("_") or not isinstance(v, dict):
            continue
        if use_filter and k not in active_hosts:
            continue

        stats = compute_node_stats(k, v, history, now=now)
        nodes_stats[k] = stats

        is_egress = (k in egress_hosts) if use_filter else True
        if is_egress:
            tot_today += stats["today_gb"]
            tot_yesterday += stats["yesterday_gb"]
            tot_week += stats["this_week_gb"]
            tot_month += stats["this_month_gb"]
            tot_year += stats["this_year_gb"]
            tot_total += stats["total_gb"]

            if primary_candidate is None or stats["total_gb"] > primary_candidate.get("total_gb", 0):
                primary_candidate = stats
                primary_guidance = dict(stats["guidance"])
                primary_guidance["total_gb"] = stats["total_gb"]

    if primary_guidance is None:
        if nodes_stats:
            first_stat = next(iter(nodes_stats.values()))
            primary_guidance = dict(first_stat["guidance"])
            primary_guidance["total_gb"] = first_stat["total_gb"]
        else:
            primary_guidance = generate_usage_guidance(tot_month, tot_total, "", "", tot_today, now=now)

    # 关键闭环：修正 primary_guidance 中的 remaining_gb 与 daily_budget_gb，
    # 确保与聚合的 tot_total 和 tot_month 绝对一致（SSOT 对齐）
    if primary_guidance and tot_total > 0:
        tot_total_r = round(tot_total, 2)
        tot_month_r = round(tot_month, 2)
        actual_remaining = max(0.0, round(tot_total_r - tot_month_r, 2))
        primary_guidance["remaining_gb"] = actual_remaining
        days_rem = primary_guidance.get("days_remaining", 30)
        daily_budget = round(actual_remaining / days_rem, 2) if days_rem > 0 else 0.0
        primary_guidance["daily_budget_gb"] = daily_budget
        primary_guidance["total_gb"] = tot_total_r
        ratio = (tot_today / daily_budget) if daily_budget > 0 else 0.0
        primary_guidance["pacing_ratio"] = round(ratio, 2)
        primary_guidance["today_used_gb"] = round(tot_today, 2)

        if (tot_month / tot_total) >= 0.90:
            primary_guidance["pace"] = "critical"
            primary_guidance["badge"] = "紧急预警"
            primary_guidance["text"] = f"月度流量仅剩 {actual_remaining} GB（已用 {round(tot_month/tot_total*100, 1)}%），请注意控制大流量消耗或调高保护阈值。"
        elif daily_budget > 0 and ratio > 1.2:
            primary_guidance["pace"] = "heavy"
            primary_guidance["badge"] = "今日消耗偏快"
            primary_guidance["text"] = f"今日已用 {round(tot_today, 2)} GB，略超出建议日均配额（{daily_budget} GB/天），建议留意视频画质或后台下载。"
        elif daily_budget > 0 and ratio < 0.5:
            primary_guidance["pace"] = "abundant"
            primary_guidance["badge"] = "余量极其充裕"
            if days_rem <= 2:
                primary_guidance["text"] = f"离重置还有 {days_rem} 天，剩余 {actual_remaining} GB。日均可用 {daily_budget} GB/天，账单周期即将切换，建议保留安全余量避免超量计费。"
            else:
                primary_guidance["text"] = f"离重置还有 {days_rem} 天，剩余 {actual_remaining} GB。日均可用 {daily_budget} GB/天，可随心看高清/测速。"
        else:
            primary_guidance["pace"] = "normal"
            primary_guidance["badge"] = "用量健康稳定"
            primary_guidance["text"] = f"离重置还有 {days_rem} 天，日均建议配额 {daily_budget} GB/天，使用节奏良好。"

    # 拓扑木桶短板分析 (Bottleneck Theory):
    # 检查是否存在专线中转机（relay），其中转剩余配额低于落地机实际可用配额
    min_relay_remaining = None
    bottleneck_relay_name = None
    if active_nodes is not None:
        for n in active_nodes:
            if n.get("role") == "relay":
                h = n.get("host") or n.get("ip")
                if h and h in nodes_stats:
                    relay_rem = nodes_stats[h]["guidance"].get("remaining_gb", 0.0)
                    if min_relay_remaining is None or relay_rem < min_relay_remaining:
                        min_relay_remaining = relay_rem
                        bottleneck_relay_name = n.get("name") or h

    if primary_guidance and min_relay_remaining is not None:
        cur_rem = primary_guidance.get("remaining_gb", float("inf"))
        if min_relay_remaining < cur_rem:
            primary_guidance["bottleneck"] = {
                "is_relay_bottleneck": True,
                "relay_name": bottleneck_relay_name,
                "relay_remaining_gb": min_relay_remaining,
                "egress_remaining_gb": cur_rem,
            }
            primary_guidance["pace"] = "warn"
            primary_guidance["badge"] = "跳板短板预警"
            primary_guidance["text"] = (
                f"链路受中转跳板「{bottleneck_relay_name}」配额限制，实际有效可用仅剩 {min_relay_remaining} GB "
                f"（落地机尚余 {cur_rem} GB），请优先留意跳板流量。"
            )

    return {
        "total": {
            "today_gb": round(tot_today, 2),
            "yesterday_gb": round(tot_yesterday, 2),
            "this_week_gb": round(tot_week, 2),
            "this_month_gb": round(tot_month, 2),
            "this_year_gb": round(tot_year, 2),
            "total_quota_gb": round(tot_total, 2),
            "guidance": primary_guidance,
        },
        "nodes": nodes_stats,
        "updated_at": now.isoformat(),
    }
