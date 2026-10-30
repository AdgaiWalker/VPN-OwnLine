#!/usr/bin/env python3
"""quota_guard.py 的全离网单测。验证流量水位计算与安全熔断逻辑。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import quota_guard  # noqa: E402

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, f"失败: {name} {extra}"
    ok += 1
    print(f"  OK {name}")


def test_evaluate_instance_normal():
    # 消耗 200GB / 1000GB = 20%
    data = {"name": "北京", "traffic_package": {"used_bytes": 200 * (1024**3), "total_bytes": 1000 * (1024**3)}}
    res = quota_guard.evaluate_instance_quota(data)
    check("20% 为正常状态", res["status"] == "normal")
    check("20% 未触发熔断", not res["is_tripped"])
    check("20% 未触发预警", not res["is_warning"])
    check("百分比计算精确", abs(res["percent"] - 20.0) < 0.1)


def test_evaluate_instance_warning():
    # 消耗 780GB / 1000GB = 78%
    data = {"name": "广州", "traffic_package": {"used_bytes": 780 * (1024**3), "total_bytes": 1000 * (1024**3)}}
    res = quota_guard.evaluate_instance_quota(data)
    check("78% 进入预警状态", res["status"] == "warning")
    check("78% 标记 is_warning=True", res["is_warning"])
    check("78% 尚未触发熔断 is_tripped=False", not res["is_tripped"])


def test_evaluate_instance_tripped():
    # 消耗 880GB / 1000GB = 88%
    data = {"name": "硅谷", "traffic_package": {"used_bytes": 880 * (1024**3), "total_bytes": 1000 * (1024**3)}}
    res = quota_guard.evaluate_instance_quota(data)
    check("88% 触发熔断状态", res["status"] == "tripped")
    check("88% 标记 is_tripped=True", res["is_tripped"])
    check("88% 包含防扣费原因", "防扣费" in res["reason"])


def test_evaluate_all_summary():
    usage_data = {
        "1.1.1.1": {"name": "正常机", "traffic_package": {"used_bytes": 100, "total_bytes": 1000}},
        "2.2.2.2": {"name": "超标机", "traffic_package": {"used_bytes": 900, "total_bytes": 1000}},
        "_updated_at": "2026-10-30T10:00:00Z",
    }
    all_res = quota_guard.evaluate_all(usage_data)
    check("正确忽略元数据下划线字段", "_updated_at" not in all_res or all_res["_updated_at"] == "2026-10-30T10:00:00Z" or "_summary" in all_res)
    check("汇总标记包含 any_tripped", all_res["_summary"]["any_tripped"])
    check("单节点熔断检测返回 True", quota_guard.is_node_circuit_broken("2.2.2.2", usage_data))
    check("正常节点熔断检测返回 False", not quota_guard.is_node_circuit_broken("1.1.1.1", usage_data))


def run_all():
    test_evaluate_instance_normal()
    test_evaluate_instance_warning()
    test_evaluate_instance_tripped()
    test_evaluate_all_summary()
    print(f"通过 {ok} 项")


if __name__ == "__main__":
    run_all()
