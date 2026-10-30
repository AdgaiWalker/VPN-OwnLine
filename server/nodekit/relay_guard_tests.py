#!/usr/bin/env python3
"""relay_guard.py 的全离网单测。验证双落地故障倒换状态机与防抖回切算法。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import relay_guard  # noqa: E402

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, f"失败: {name} {extra}"
    ok += 1
    print(f"  OK {name}")


def test_engine_init():
    engine = relay_guard.RelayFailoverEngine("43.153.56.137", 443, "43.163.4.104", 8443)
    st = engine.get_state()
    check("初始化默认活跃目标为主落地", st["active_target"] == "43.153.56.137")
    check("初始化失败计数为0", st["consecutive_primary_fails"] == 0)


def test_failover_single_jitter():
    engine = relay_guard.RelayFailoverEngine("43.153.56.137", 443, "43.163.4.104", 8443, fail_threshold=2)
    # 模拟单次探测失败（偶发丢包）
    switched, target, reason = engine.evaluate_step(primary_ok=False, fallback_ok=True)
    check("单次偶发失败不触发倒换(防抖)", not switched)
    check("当前目标仍保持主落地", target == "43.153.56.137")
    check("失败计数累计为1", engine.consecutive_primary_fails == 1)

    # 下一轮恢复正常
    switched, target, reason = engine.evaluate_step(primary_ok=True, fallback_ok=True)
    check("恢复后不倒换", not switched)
    check("失败计数清零", engine.consecutive_primary_fails == 0)


def test_failover_trigger():
    engine = relay_guard.RelayFailoverEngine("43.153.56.137", 443, "43.163.4.104", 8443, fail_threshold=2)
    # 连续 2 次探测失败
    engine.evaluate_step(primary_ok=False, fallback_ok=True)
    switched, target, reason = engine.evaluate_step(primary_ok=False, fallback_ok=True)
    check("连续2次失败触发自动倒换", switched)
    check("活动目标切换至备用新加坡", target == "43.163.4.104")
    check("记录倒换原因", "自动故障倒换至备用落地" in reason)
    check("历史记录包含切换条目", len(engine.switch_history) == 1)


def test_dual_down_protection():
    engine = relay_guard.RelayFailoverEngine("43.153.56.137", 443, "43.163.4.104", 8443, fail_threshold=2)
    # 主备全挂时，不颠簸切换
    engine.evaluate_step(primary_ok=False, fallback_ok=False)
    switched, target, reason = engine.evaluate_step(primary_ok=False, fallback_ok=False)
    check("两台全挂时不颠簸倒换", not switched)
    check("保持原目标", target == "43.153.56.137")


def test_failback_hysteresis():
    engine = relay_guard.RelayFailoverEngine("43.153.56.137", 443, "43.163.4.104", 8443, fail_threshold=2, recover_threshold=3)
    # 先触发切换至备用
    engine.evaluate_step(primary_ok=False, fallback_ok=True)
    engine.evaluate_step(primary_ok=False, fallback_ok=True)
    assert engine.active_target == "43.163.4.104"

    # 主机恢复 1 次 -> 不回切
    switched, target, _ = engine.evaluate_step(primary_ok=True, fallback_ok=True)
    check("主机恢复第1次不立即回切", not switched and target == "43.163.4.104")

    # 主机恢复 2 次 -> 不回切
    switched, target, _ = engine.evaluate_step(primary_ok=True, fallback_ok=True)
    check("主机恢复第2次仍不回切", not switched and target == "43.163.4.104")

    # 主机恢复第 3 次 -> 达到阈值，触发回切
    switched, target, reason = engine.evaluate_step(primary_ok=True, fallback_ok=True)
    check("主机连续3次健康触发优雅回切", switched)
    check("活动目标恢复为主落地", target == "43.153.56.137")
    check("回切原因记录清晰", "自动回切至主落地" in reason)
    check("历史记录包含两次切换", len(engine.switch_history) == 2)


def run_all():
    test_engine_init()
    test_failover_single_jitter()
    test_failover_trigger()
    test_dual_down_protection()
    test_failback_hysteresis()
    print(f"通过 {ok} 项")


if __name__ == "__main__":
    run_all()
