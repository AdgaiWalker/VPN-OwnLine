#!/usr/bin/env python3
"""节点全生命周期状态机与排空控制器（纯标准库，零外部依赖）。

管理节点的四个生命周期状态：
  1. active     - 正常活跃：健康且未临近到期，正常进订阅。
  2. draining   - 优雅排空：距到期 <= drain_days（默认 7 天）或人工设定排空，
                  从订阅中移出避免新连接进入，存量连接自然消化。
  3. expired    - 已过期：当前时间已超过 expire_at，禁止路由。
  4. disabled   - 已停用：管理员人工停用。

所有函数均为纯函数，支持传入 now_ts 方便无网络单测。
"""
import datetime
import time

DEFAULT_DRAIN_DAYS = 0


def parse_timestamp(val):
    """解析日期时间值（支持 int/float 时间戳、ISO 8601 字符串、YYYY-MM-DD 日期）。
    返回 UTC 时间戳 (float) 或 None。
    """
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        # 纯日期格式 YYYY-MM-DD
        if len(val) == 10 and val.count("-") == 2:
            try:
                dt = datetime.datetime.strptime(val, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
                return dt.timestamp()
            except Exception:
                pass
        # ISO 8601 格式
        try:
            norm = val.replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(norm)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt.timestamp()
        except Exception:
            pass
    return None


def get_days_until_expiration(node, now_ts=None):
    """计算距离到期剩余天数。返回 int（剩余整天数，已过期为负数或0）或 None。"""
    if not isinstance(node, dict):
        return None
    exp_val = (node.get("lifecycle") or {}).get("expire_at") or node.get("expire_at")
    exp_ts = parse_timestamp(exp_val)
    if exp_ts is None:
        return None
    cur_ts = now_ts if now_ts is not None else time.time()
    diff_sec = exp_ts - cur_ts
    return int(diff_sec // 86400) if diff_sec < 0 else int((diff_sec + 86399) // 86400)


def get_lifecycle_state(node, now_ts=None, drain_days=DEFAULT_DRAIN_DAYS):
    """根据节点配置与当前时间计算生命周期状态。
    
    返回字典:
      {
        "state": "active" | "draining" | "expired" | "disabled",
        "days_left": int or None,
        "expire_at_ts": float or None,
        "is_eligible_for_sub": bool,
        "badge_text": str,
        "reason": str
      }
    """
    if not isinstance(node, dict):
        return {
            "state": "disabled",
            "days_left": None,
            "expire_at_ts": None,
            "is_eligible_for_sub": False,
            "badge_text": "无效节点",
            "reason": "节点数据非法",
        }

    # 1. 明确停用
    if node.get("enabled") is False:
        return {
            "state": "disabled",
            "days_left": None,
            "expire_at_ts": None,
            "is_eligible_for_sub": False,
            "badge_text": "已停用",
            "reason": "管理员已停用此节点",
        }

    # 2. 检查到期时间
    lifecycle_cfg = node.get("lifecycle") or {}
    manual_state = lifecycle_cfg.get("state")
    exp_val = lifecycle_cfg.get("expire_at") or node.get("expire_at")
    exp_ts = parse_timestamp(exp_val)
    cur_ts = now_ts if now_ts is not None else time.time()

    # 人工强制指定了 draining
    if manual_state == "draining":
        days_left = get_days_until_expiration(node, now_ts=cur_ts)
        return {
            "state": "draining",
            "days_left": days_left,
            "expire_at_ts": exp_ts,
            "is_eligible_for_sub": False,
            "badge_text": f"{days_left}天后下线(排空中)" if days_left is not None else "优雅排空中",
            "reason": lifecycle_cfg.get("drain_reason") or "人工标记优雅排空",
        }

    # 计算时间状态
    if exp_ts is not None:
        diff_sec = exp_ts - cur_ts
        days_left = int(diff_sec // 86400) if diff_sec < 0 else int((diff_sec + 86399) // 86400)

        # 已过期
        if cur_ts >= exp_ts:
            return {
                "state": "expired",
                "days_left": 0,
                "expire_at_ts": exp_ts,
                "is_eligible_for_sub": False,
                "badge_text": "已过期",
                "reason": "服务器已过服务期",
            }

        # 临近到期进入 draining
        if diff_sec <= (drain_days * 86400):
            return {
                "state": "draining",
                "days_left": days_left,
                "expire_at_ts": exp_ts,
                "is_eligible_for_sub": False,
                "badge_text": f"{days_left}天后到期(已排空)",
                "reason": f"距离停机不足 {drain_days} 天，自动移出订阅排空",
            }

        # 虽有到期日但还在安全期（> drain_days）
        return {
            "state": "active",
            "days_left": days_left,
            "expire_at_ts": exp_ts,
            "is_eligible_for_sub": True,
            "badge_text": f"{days_left}天后到期",
            "reason": "正常服役中",
        }

    # 没有配置到期日，默认活跃
    return {
        "state": "active",
        "days_left": None,
        "expire_at_ts": None,
        "is_eligible_for_sub": True,
        "badge_text": "正常",
        "reason": "长期有效节点",
    }


def is_in_subscription(node, now_ts=None, drain_days=DEFAULT_DRAIN_DAYS):
    """节点是否允许出现在客户端订阅中（结合生命周期状态与 BAD_HEALTH 判断）。"""
    bad_health = frozenset({"port", "tls", "proxy", "role_mismatch", "landing", "blocked", "timeout"})
    if (node or {}).get("health") in bad_health:
        return False
    st = get_lifecycle_state(node, now_ts=now_ts, drain_days=drain_days)
    return st["is_eligible_for_sub"]
