#!/usr/bin/env python3
"""quota_guard.py 的全离网单测。验证真实用量解析与物理断流逻辑。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import quota_guard  # noqa: E402

ok = 0


def check(name, cond, extra=""):
    global ok
    assert cond, f"失败: {name} {extra}"
    ok += 1
    print(f"  OK {name}")


def test_evaluate_instance_real_format():
    # 真实线上格式：单位 GB (如硅谷 69.89 / 512.0 = 13.65% ≈ 13.7%)
    data_live = {"used": 69.89, "total": 512.0, "region": "硅谷"}
    res = quota_guard.evaluate_instance_quota(data_live)
    check("真实线上格式 13.7% 为正常状态", res["status"] == "normal")
    check("真实线上格式未触发熔断", not res["is_tripped"])
    check("真实线上格式精确解析 used_gb", res["used_gb"] == 69.89)
    check("真实线上格式精确解析 total_gb", res["total_gb"] == 512.0)
    check("真实线上格式百分比正确 (13.7%)", abs(res["percent"] - 13.7) < 0.1)

    # 真实线上格式超标 (450GB / 500GB = 90.0%)
    data_tripped = {"used": 450.0, "total": 500.0, "region": "北京"}
    res_t = quota_guard.evaluate_instance_quota(data_tripped)
    check("真实线上格式 90% 触发熔断", res_t["status"] == "tripped")
    check("真实线上格式 is_tripped=True", res_t["is_tripped"])


def test_evaluate_instance_legacy_bytes():
    # 兼容格式：traffic_package 字节
    data = {"name": "北京", "traffic_package": {"used_bytes": 200 * (1024**3), "total_bytes": 1000 * (1024**3)}}
    res = quota_guard.evaluate_instance_quota(data)
    check("字节格式 20% 为正常状态", res["status"] == "normal")
    check("字节格式未触发熔断", not res["is_tripped"])

    data_w = {"name": "广州", "traffic_package": {"used_bytes": 780 * (1024**3), "total_bytes": 1000 * (1024**3)}}
    res_w = quota_guard.evaluate_instance_quota(data_w)
    check("字节格式 78% 进入预警状态", res_w["status"] == "warning")

    data_t = {"name": "硅谷", "traffic_package": {"used_bytes": 880 * (1024**3), "total_bytes": 1000 * (1024**3)}}
    res_t = quota_guard.evaluate_instance_quota(data_t)
    check("字节格式 88% 触发熔断", res_t["status"] == "tripped")


def test_evaluate_all_summary():
    usage_data = {
        "1.1.1.1": {"name": "正常机", "used": 50.0, "total": 500.0},
        "2.2.2.2": {"name": "超标机", "used": 450.0, "total": 500.0},
        "_ts": "2026-10-31T00:00:00Z",
    }
    all_res = quota_guard.evaluate_all(usage_data)
    check("正确忽略元数据下划线字段", "_ts" not in all_res)
    check("汇总标记包含 any_tripped", all_res["_summary"]["any_tripped"])
    check("单节点熔断检测返回 True", quota_guard.is_node_circuit_broken("2.2.2.2", usage_data))
    check("正常节点熔断检测返回 False", not quota_guard.is_node_circuit_broken("1.1.1.1", usage_data))


def test_enforce_quota():
    mock_cmds = []

    def mock_runner(cmd, **kwargs):
        mock_cmds.append(cmd)
        class Dummy:
            returncode = 0
            stdout = ""
            stderr = ""
        return Dummy()

    nodes = [
        {"name": "北京中转", "host": "49.233.210.101", "role": "relay", "source": "builtin", "ssh_user": "root"},
        {"name": "硅谷直连", "host": "43.153.56.137", "role": "exit", "source": "builtin", "ssh_user": "ubuntu"},
    ]

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_path = tf.name

    try:
        # 1. 模拟北京中转超标 90%
        usage_tripped = {
            "49.233.210.101": {"used": 450.0, "total": 500.0},
            "43.153.56.137": {"used": 50.0, "total": 500.0},
        }
        actions = quota_guard.enforce_quota(nodes, usage_tripped, runner=mock_runner, state_file=state_path)
        check("触发停机断流动作 1 次", len(actions) == 1)
        check("停机目标为超标机", actions[0]["ip"] == "49.233.210.101" and actions[0]["action"] == "stop")
        check("执行了远程停机命令", any("c3lzdGVtY3RsIHN0b3Agc2luZy1ib3g=" in str(c) or "stop" in str(c) for c in mock_cmds))

        # 2. 再次执行相同用量，已停机不重复执行
        mock_cmds.clear()
        actions_dup = quota_guard.enforce_quota(nodes, usage_tripped, runner=mock_runner, state_file=state_path)
        check("已处于断流状态不重复发停机命令", len(actions_dup) == 0 and len(mock_cmds) == 0)

        # 3. 模拟新周期流量恢复正常
        mock_cmds.clear()
        usage_recovered = {
            "49.233.210.101": {"used": 10.0, "total": 500.0},
            "43.153.56.137": {"used": 50.0, "total": 500.0},
        }
        actions_rec = quota_guard.enforce_quota(nodes, usage_recovered, runner=mock_runner, state_file=state_path)
        check("触发恢复启动动作 1 次", len(actions_rec) == 1)
        check("启动目标为恢复机", actions_rec[0]["ip"] == "49.233.210.101" and actions_rec[0]["action"] == "start")
        check("执行了远程拉起命令", any("c3lzdGVtY3RsIHN0YXJ0IHNpbmctYm94" in str(c) or "start" in str(c) for c in mock_cmds))
    finally:
        if os.path.exists(state_path):
            os.remove(state_path)


def run_all():
    test_evaluate_instance_real_format()
    test_evaluate_instance_legacy_bytes()
    test_evaluate_all_summary()
    test_enforce_quota()
    print(f"通过 {ok} 项")


if __name__ == "__main__":
    run_all()
