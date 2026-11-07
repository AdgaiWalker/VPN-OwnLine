#!/usr/bin/env python3
"""quota_guard.py 的全离网单测。验证真实用量解析与物理断流逻辑。"""
import base64
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        "_ts": datetime.now(timezone.utc).isoformat(),
    }
    all_res = quota_guard.evaluate_all(usage_data)
    check("正确忽略元数据下划线字段", "_ts" not in all_res)
    check("汇总标记包含 any_tripped", all_res["_summary"]["any_tripped"])
    check("单节点熔断检测返回 True", quota_guard.is_node_circuit_broken("2.2.2.2", usage_data))
    check("正常节点熔断检测返回 False", not quota_guard.is_node_circuit_broken("1.1.1.1", usage_data))


def remote_script(cmd):
    last = cmd[-1]
    if last.startswith("echo ") and " | base64 -d | bash" in last:
        return base64.b64decode(last.split()[1]).decode()
    return last


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
        {"name": "北京中转", "host": "198.51.100.10", "role": "relay", "source": "builtin", "ssh_user": "root", "quota_control_managed": True},
        {"name": "硅谷直连", "host": "203.0.113.10", "role": "exit", "source": "builtin", "ssh_user": "ubuntu", "quota_control_managed": True},
    ]

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        state_path = tf.name

    try:
        # 1. 模拟北京中转超标 90%
        usage_tripped = {
            "_ts": datetime.now(timezone.utc).isoformat(),
            "198.51.100.10": {"used": 450.0, "total": 500.0},
            "203.0.113.10": {"used": 50.0, "total": 500.0},
        }
        actions = quota_guard.enforce_quota(nodes, usage_tripped, runner=mock_runner, state_file=state_path)
        check("触发停机断流动作 1 次", len(actions) == 1)
        check("停机目标为超标机", actions[0]["ip"] == "198.51.100.10" and actions[0]["action"] == "stop")
        check("执行了远程停机命令", any("systemctl stop sing-box" in remote_script(c) for c in mock_cmds))

        stop_script = remote_script(mock_cmds[0])
        check("停机前设置保护标记", stop_script.index("touch /var/lib/ownline/quota-paused") < stop_script.index("systemctl stop sing-box"))
        check("保护停机独立获取短锁", "flock -x -w 5 /run/ownline-service.lock" in stop_script)

        # 2. 再次执行相同用量，已停机不重复执行
        mock_cmds.clear()
        actions_dup = quota_guard.enforce_quota(nodes, usage_tripped, runner=mock_runner, state_file=state_path)
        check("已处于断流状态不重复发停机命令", len(actions_dup) == 0 and len(mock_cmds) == 0)

        # 3. 模拟新周期流量恢复正常
        mock_cmds.clear()
        usage_recovered = {
            "_ts": datetime.now(timezone.utc).isoformat(),
            "198.51.100.10": {"used": 10.0, "total": 500.0},
            "203.0.113.10": {"used": 50.0, "total": 500.0},
        }
        actions_rec = quota_guard.enforce_quota(nodes, usage_recovered, runner=mock_runner, state_file=state_path)
        check("触发恢复启动动作 1 次", len(actions_rec) == 1)
        check("启动目标为恢复机", actions_rec[0]["ip"] == "198.51.100.10" and actions_rec[0]["action"] == "start")
        check("执行了远程拉起命令", any("systemctl start sing-box" in remote_script(c) for c in mock_cmds))
        start_script = remote_script(mock_cmds[0])
        check("恢复先移除阻止启动的标记", start_script.index("rm -f /var/lib/ownline/quota-paused") < start_script.index("systemctl start sing-box"))
        check("恢复失败时重新设置标记", "else touch /var/lib/ownline/quota-paused" in start_script)
    finally:
        if os.path.exists(state_path):
            os.remove(state_path)


def test_enforce_failures_and_unknown_usage():
    node = {"name": "测试节点", "host": "192.0.2.10", "quota_control_managed": True}
    other = {"name": "其他节点", "host": "192.0.2.11", "quota_control_managed": True}
    high = {"_ts": datetime.now(timezone.utc).isoformat(), node["host"]: {"used": 90, "total": 100}}
    low = {"_ts": datetime.now(timezone.utc).isoformat(), node["host"]: {"used": 0, "total": 100}}
    calls = []

    def success(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    def failed(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 255)

    def timeout(cmd, **kwargs):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, 15)

    with tempfile.TemporaryDirectory() as tmp, patch.object(quota_guard, "logger") as log:
        state_path = os.path.join(tmp, "state.json")

        def stopped():
            with open(state_path, encoding="utf-8") as f:
                return json.load(f)["stopped_ips"]

        for runner in (failed, timeout):
            actions = quota_guard.enforce_quota([node], high, runner=runner, state_file=state_path)
            check("停机失败返回错误且未记录已停机", actions[0].get("ok") is False and stopped() == [])
        actions = quota_guard.enforce_quota([node], high, runner=success, state_file=state_path)
        check("失败后下轮重试停机并持久化成功状态", actions[0]["action"] == "stop" and stopped() == [node["host"]])

        for bad in (None, {}, {"used": "bad", "total": 100}, {"used": 0},
                    {"used": 0, "total": 0}, {"used": -1, "total": 100},
                    {"used": float("nan"), "total": 100}, {"used": 1, "total": float("inf")},
                    {"traffic_package": {"used_bytes": "bad", "total_bytes": 100}},
                    {"traffic_package": {"used_bytes": 0, "total_bytes": -1}}):
            calls.clear()
            # 模拟其他地区采集成功、已熔断节点数据缺失或损坏。
            partial = {"_ts": datetime.now(timezone.utc).isoformat(), other["host"]: {"used": 10, "total": 100}}
            if bad is not None:
                partial[node["host"]] = bad
            actions = quota_guard.enforce_quota([node, other], partial, runner=success, state_file=state_path)
            check("未知用量保留熔断状态且不启动", not actions and not calls and stopped() == [node["host"]])
            check("缺失或无效用量标为 unknown", quota_guard.evaluate_instance_quota(bad)["status"] == "unknown")

        for runner in (failed, timeout):
            actions = quota_guard.enforce_quota([node], low, runner=runner, state_file=state_path)
            check("恢复失败保留已熔断状态", actions[0].get("ok") is False and stopped() == [node["host"]])
        actions = quota_guard.enforce_quota([node], low, runner=success, state_file=state_path)
        check("有效零用量允许恢复且下轮重试成功", actions[0]["action"] == "start" and stopped() == [])
        check("执行失败写入错误日志", any(c.args[0] == "ERROR" for c in log.log.call_args_list))

        calls.clear()
        # 单个节点异常不应阻断后面的超标节点。
        def mixed(cmd, **kwargs):
            if any(node["host"] in arg for arg in cmd):
                return timeout(cmd, **kwargs)
            return success(cmd, **kwargs)
        both_high = {n["host"]: {"used": 90, "total": 100} for n in (node, other)}
        both_high["_ts"] = datetime.now(timezone.utc).isoformat()
        actions = quota_guard.enforce_quota([node, other], both_high, runner=mixed, state_file=state_path)
        check("单节点异常不阻断其他节点熔断", len(actions) == 2 and stopped() == [other["host"]])

        with patch.object(quota_guard, "repair", None):
            actions = quota_guard.enforce_quota([node], high, runner=success, state_file=state_path)
            check("远程执行器不可用不记录停机成功", actions[0].get("ok") is False and stopped() == [other["host"]])


def test_threshold_freshness_and_ownership():
    with tempfile.TemporaryDirectory() as tmp, patch.object(quota_guard, "QUOTA_SETTINGS_FILE", os.path.join(tmp, "settings.json")):
        check("默认阈值为 85", quota_guard.quota_threshold() == 85)
        for invalid in (None, True, 0, 101, 85.5, "85"):
            try:
                quota_guard.save_quota_threshold(invalid)
                raise AssertionError("无效阈值应被拒绝")
            except ValueError:
                pass
        quota_guard.save_quota_threshold(60)
        check("用户自定义阈值已保存", quota_guard.quota_threshold() == 60)
        node = {"host": "192.0.2.15", "quota_control_managed": True}
        now = datetime.now(timezone.utc)
        fresh = {"_ts": now.isoformat(), node["host"]: {"used": 70, "total": 100}}
        stale = {"_ts": (now - timedelta(hours=1)).isoformat(), node["host"]: {"used": 10, "total": 100}}
        state = os.path.join(tmp, "state.json")
        calls = []
        def run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)
        unmanaged = {"host": node["host"]}
        check("未确认服务归属不自动停止", not quota_guard.enforce_quota([unmanaged], fresh, runner=run, state_file=state))
        windows = {"host": node["host"], "os": "windows", "quota_control_managed": True}
        check("Windows 停止进程会影响其他服务时不自动保护", not quota_guard.enforce_quota([windows], fresh, runner=run, state_file=state))
        check("自定义阈值适用于状态判断", quota_guard.evaluate_all(fresh)[node["host"]]["is_tripped"])
        check("自定义阈值适用于订阅判断", quota_guard.is_node_circuit_broken(node["host"], fresh))
        check("自定义阈值适用于自动停机", quota_guard.enforce_quota([node], fresh, runner=run, state_file=state)[0]["action"] == "stop")
        calls.clear()
        check("过期用量不触发恢复", not quota_guard.enforce_quota([node], stale, runner=run, state_file=state) and not calls)
        check("过期用量不显示为实时数值", quota_guard.evaluate_all(stale)[node["host"]]["status"] == "unknown")
        check("缺失时间戳不可用于保护决策", not quota_guard.usage_is_fresh({node["host"]: {"used": 0, "total": 100}}))


def test_persistent_service_guard_and_restart():
    root = Path(__file__).resolve().parents[2]
    for file in (root / "deploy/systemd/sing-box.service", root / "server/addnode.sh"):
        check("新装 systemd 服务遵守保护停机标记", "ConditionPathExists=!/var/lib/ownline/quota-paused" in file.read_text())
    with tempfile.TemporaryDirectory() as tmp:
        bindir = Path(tmp) / "bin"
        bindir.mkdir()
        state_dir = Path(tmp) / "ownline"
        state_dir.mkdir()
        marker = state_dir / "quota-paused"
        (bindir / "flock").write_text("#!/bin/sh\nshift 4\nexec \"$@\"\n")
        (bindir / "systemctl").write_text(
            "#!/bin/sh\ncase \"$1\" in\n"
            "start) exit \"$START_EXIT\";;\n"
            "stop) exit \"$STOP_EXIT\";;\n"
            "is-active) [ \"$ACTIVE\" = 1 ];;\n"
            "show) printf '%s\\n' \"$SHOW_STATE\";;\n"
            "esac\n")
        for p in bindir.iterdir():
            p.chmod(0o755)
        env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ.get("PATH", ""),
                   START_EXIT="0", STOP_EXIT="0", ACTIVE="0", SHOW_STATE="inactive")
        def execute(node, command, runner, timeout):
            isolated = command.replace("/run/ownline-service.lock", str(Path(tmp) / "lock"))
            isolated = isolated.replace("/var/lib/ownline", str(state_dir))
            return subprocess.run(["sh", "-c", isolated], env=env, capture_output=True)
        with patch.object(quota_guard, "repair", SimpleNamespace(execute_remote=execute)):
            env["SHOW_STATE"] = "active"
            check("停止命令返回成功但服务仍运行时不声称成功", quota_guard.stop_node_proxy({}).returncode != 0 and marker.exists())
            env["SHOW_STATE"] = "inactive"
            check("已确认服务停止后才报告成功", quota_guard.stop_node_proxy({}).returncode == 0 and marker.exists())
            env["ACTIVE"] = "0"
            check("启动命令返回成功但服务未运行时恢复保护标记", quota_guard.start_node_proxy({}).returncode != 0 and marker.exists())
            env["START_EXIT"] = "1"
            check("启动命令失败时保留保护标记", quota_guard.start_node_proxy({}).returncode != 0 and marker.exists())
            env["START_EXIT"] = "0"
            env["ACTIVE"] = "1"
            check("仅真实运行成功后移除保护标记", quota_guard.start_node_proxy({}).returncode == 0 and not marker.exists())


def test_addnode_existing_service_preflight():
    script = (Path(__file__).resolve().parents[1] / "addnode.sh").read_text()
    check("远程检测在下载依赖之前执行", script.index("目标服务器的既有服务检查未通过") < script.index("检查目标机依赖"))
    block = script.split("REMOTE=$(cat <<'EOS'\n", 1)[1].split("mkdir /opt/sing-box", 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        bindir = directory / "bin"
        bindir.mkdir()
        systemctl = bindir / "systemctl"
        systemctl.write_text("#!/bin/sh\ncase \"$1\" in list-units) exit \"$LIST_EXIT\";; is-active) exit \"$ACTIVE_EXIT\";; esac\n")
        systemctl.chmod(0o755)
        env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ.get("PATH", ""),
                   LIST_EXIT="0", ACTIVE_EXIT="1")
        for path in ("/opt/sing-box", "/etc/systemd/system", "/lib/systemd/system", "/usr/lib/systemd/system"):
            block = block.replace(path, str(directory) + path)
        def inspect():
            return subprocess.run(["sh", "-c", block], env=env, capture_output=True)
        check("空白目标通过二次只读检查", inspect().returncode == 0)
        env["LIST_EXIT"] = "1"
        check("无法检查系统服务时安全失败", inspect().returncode != 0)
        env["LIST_EXIT"] = "0"
        env["ACTIVE_EXIT"] = "0"
        check("已有运行中服务时安全失败", inspect().returncode != 0)
        env["ACTIVE_EXIT"] = "1"
        service = directory / "etc/systemd/system/sing-box.service"
        service.parent.mkdir(parents=True)
        service.write_text("existing")
        check("已有服务文件时安全失败且不覆盖", inspect().returncode != 0 and service.read_text() == "existing")


def run_all():
    test_evaluate_instance_real_format()
    test_evaluate_instance_legacy_bytes()
    test_evaluate_all_summary()
    test_enforce_quota()
    test_enforce_failures_and_unknown_usage()
    test_threshold_freshness_and_ownership()
    test_persistent_service_guard_and_restart()
    test_addnode_existing_service_preflight()
    print(f"通过 {ok} 项")


if __name__ == "__main__":
    run_all()
