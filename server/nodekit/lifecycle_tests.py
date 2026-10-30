#!/usr/bin/env python3
"""lifecycle.py 的全离网单测。测试生命周期状态机、排空与到期逻辑。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import lifecycle  # noqa: E402

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, f"失败: {name} {extra}"
    ok += 1
    print(f"  OK {name}")


def test_parse_timestamp():
    # 时间戳数值
    check("时间戳浮点/整数解析", lifecycle.parse_timestamp(1700000000) == 1700000000.0)
    # YYYY-MM-DD
    ts = lifecycle.parse_timestamp("2026-11-12")
    check("YYYY-MM-DD 纯日期解析", ts is not None and ts > 1700000000)
    # ISO 8601 带 Z
    ts_iso = lifecycle.parse_timestamp("2026-11-12T00:00:00Z")
    check("ISO 8601 带 Z 解析", ts_iso == ts)
    # 非法值安全返回 None
    check("None 输入安全返回 None", lifecycle.parse_timestamp(None) is None)
    check("空字符串安全返回 None", lifecycle.parse_timestamp("") is None)
    check("非法乱码字符串安全返回 None", lifecycle.parse_timestamp("invalid-date") is None)


def test_get_days_until_expiration():
    base_ts = 1762905600.0  # 假设基准时间 2025-11-12 00:00:00
    node_future = {"expire_at": base_ts + 86400 * 10}  # 10天后
    node_past = {"expire_at": base_ts - 86400 * 2}  # 2天前
    node_none = {"name": "永久节点"}

    check("10天后到期计算正确", lifecycle.get_days_until_expiration(node_future, now_ts=base_ts) == 10)
    check("已过期天数计算正确", lifecycle.get_days_until_expiration(node_past, now_ts=base_ts) == -2)
    check("无到期时间返回 None", lifecycle.get_days_until_expiration(node_none, now_ts=base_ts) is None)


def test_lifecycle_states():
    now = 1762905600.0  # 基准时间

    # 1. 禁用状态
    n_dis = {"name": "测试", "enabled": False}
    st_dis = lifecycle.get_lifecycle_state(n_dis, now_ts=now)
    check("enabled=False 状态为 disabled", st_dis["state"] == "disabled" and not st_dis["is_eligible_for_sub"])

    # 2. 正常长期活跃
    n_act = {"name": "硅谷", "enabled": True}
    st_act = lifecycle.get_lifecycle_state(n_act, now_ts=now)
    check("无到期日状态为 active", st_act["state"] == "active" and st_act["is_eligible_for_sub"])

    # 3. 远期到期 (> 7 天) -> active
    n_far = {"name": "广州", "expire_at": now + 86400 * 13}  # 13天后
    st_far = lifecycle.get_lifecycle_state(n_far, now_ts=now, drain_days=7)
    check("13天后到期状态为 active 且进订阅", st_far["state"] == "active" and st_far["is_eligible_for_sub"])
    check("显示倒计时 Badge", "13天后到期" in st_far["badge_text"])

    # 4. 临近到期 (<= 7 天) -> draining (排空且从订阅移出)
    n_drain = {"name": "广州", "expire_at": now + 86400 * 5}  # 5天后
    st_drain = lifecycle.get_lifecycle_state(n_drain, now_ts=now, drain_days=7)
    check("5天后到期进入 draining", st_drain["state"] == "draining" and not st_drain["is_eligible_for_sub"])
    check("显示已排空 Badge", "已排空" in st_drain["badge_text"])

    # 5. 人工指定 draining
    n_manual_drain = {"name": "北京", "lifecycle": {"state": "draining", "drain_reason": "准备割接"}}
    st_manual = lifecycle.get_lifecycle_state(n_manual_drain, now_ts=now)
    check("人工指定 draining 生效", st_manual["state"] == "draining" and not st_manual["is_eligible_for_sub"])

    # 6. 已过期
    n_exp = {"name": "过期节点", "expire_at": now - 3600}
    st_exp = lifecycle.get_lifecycle_state(n_exp, now_ts=now)
    check("已过期节点状态为 expired", st_exp["state"] == "expired" and not st_exp["is_eligible_for_sub"])


def test_is_in_subscription():
    now = 1762905600.0
    # 正常健康节点
    check("健康活跃节点进订阅", lifecycle.is_in_subscription({"health": "ok"}, now_ts=now))
    # 故障节点不可进订阅
    check("BAD_HEALTH 节点不进订阅", not lifecycle.is_in_subscription({"health": "port"}, now_ts=now))
    # 排空期节点不可进订阅
    check("draining 节点不进订阅", not lifecycle.is_in_subscription({"health": "ok", "expire_at": now + 86400 * 3}, now_ts=now, drain_days=7))
    # 已过期节点不可进订阅
    check("expired 节点不进订阅", not lifecycle.is_in_subscription({"health": "ok", "expire_at": now - 100}, now_ts=now))


def run_all():
    test_parse_timestamp()
    test_get_days_until_expiration()
    test_lifecycle_states()
    test_is_in_subscription()
    print(f"通过 {ok} 项")


if __name__ == "__main__":
    run_all()
