#!/usr/bin/env python3
"""repair.py 的离线单测。全离网，通过 mock subprocess 和 verifier 验证。"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import repair  # noqa: E402


class MockCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_build_commands():
    cmd_l = repair.build_repair_command_linux()
    assert "pkill -f 3x-ui" in cmd_l, "Linux 命令应包含清理 3x-ui 进程"
    assert "sing-box check" in cmd_l, "Linux 命令应包含配置校验"
    assert "systemctl restart sing-box" in cmd_l, "Linux 命令应包含重启 sing-box"

    cmd_w = repair.build_repair_command_windows()
    assert "taskkill /F /IM 3x-ui.exe" in cmd_w, "Windows 命令应杀死 3x-ui.exe"
    assert "taskkill /F /IM xray-windows-amd64.exe" in cmd_w, "Windows 命令应杀死 xray"
    assert "schtasks /run /tn sing-box" in cmd_w, "Windows 命令应通过 schtasks 拉起服务"
    print("  OK Linux 与 Windows 自愈指令构造正确")


def test_repair_external_node():
    node = {"name": "外部节点", "source": "external", "health": "unknown"}
    r = repair.repair_node(node)
    assert r["ok"] is False
    assert "外部节点没有 SSH 控制权限" in r["detail"]
    assert r["after"] == "unknown"
    print("  OK 外部节点无权限自动跳过并说明原因")


def test_repair_linux_success():
    node = {
        "name": "广州",
        "host": "43.140.37.38",
        "port": 443,
        "health": "proxy",
        "os": "linux",
        "ssh_user": "root",
    }
    executed_cmds = []

    def mock_runner(cmd, **kwargs):
        executed_cmds.append(cmd)
        return MockCompletedProcess(0, stdout="active")

    def mock_verifier(n):
        return {
            "health": "ok",
            "exit_ip": "43.153.56.137",
            "exit_country": "US",
            "detail": "中转：经落地出网，出口 43.153.56.137 (US)",
        }

    res = repair.repair_node(node, runner=mock_runner, verifier=mock_verifier, sleep_fn=lambda _: None)
    assert res["ok"] is True
    assert res["before"] == "proxy"
    assert res["after"] == "ok"
    assert node["health"] == "ok"
    assert node["exit_ip"] == "43.153.56.137"
    assert len(executed_cmds) == 1
    # 验证 SSH 命令构造包含 root@43.140.37.38
    assert any("root@43.140.37.38" in arg for arg in executed_cmds[0])
    print("  OK Linux 节点自愈清理并验真成功")


def test_repair_windows_success():
    node = {
        "name": "新加坡",
        "host": "43.163.4.104",
        "port": 8443,
        "health": "proxy",
        "os": "windows",
        "ssh_user": "Administrator",
    }
    executed_cmds = []

    def mock_runner(cmd, **kwargs):
        executed_cmds.append(cmd)
        return MockCompletedProcess(0, stdout="SUCCESS")

    def mock_verifier(n):
        return {
            "health": "ok",
            "exit_ip": "43.163.4.104",
            "exit_country": "SG",
            "detail": "出口 43.163.4.104 (SG)",
        }

    res = repair.repair_node(node, runner=mock_runner, verifier=mock_verifier, sleep_fn=lambda _: None)
    assert res["ok"] is True
    assert res["before"] == "proxy"
    assert res["after"] == "ok"
    assert node["health"] == "ok"
    assert node["exit_ip"] == "43.163.4.104"
    assert any("Administrator@43.163.4.104" in arg for arg in executed_cmds[0])
    # 检查 Windows 专属指令
    cmd_str = executed_cmds[0][-1]
    assert "taskkill" in cmd_str and "schtasks" in cmd_str
    print("  OK Windows 节点自动识别系统并以 Administrator 修复成功")


def test_repair_config_error():
    node = {
        "name": "损坏节点",
        "host": "1.2.3.4",
        "port": 443,
        "health": "bad",
        "os": "linux",
    }

    def mock_runner(cmd, **kwargs):
        return MockCompletedProcess(12, stderr="syntax error in config.json")

    res = repair.repair_node(node, runner=mock_runner)
    assert res["ok"] is False
    assert res["after"] == "config_error"
    assert "配置语法错误" in res["detail"]
    print("  OK 配置校验失败阻断自愈并反馈明确报错")


def test_repair_verify_failed():
    node = {
        "name": "被墙节点",
        "host": "1.2.3.4",
        "port": 443,
        "health": "proxy",
        "os": "linux",
    }

    def mock_runner(cmd, **kwargs):
        return MockCompletedProcess(0, stdout="active")

    def mock_verifier(n):
        return {
            "health": "blocked",
            "detail": "代理和 SSH 都不通，可能被墙",
        }

    res = repair.repair_node(node, runner=mock_runner, verifier=mock_verifier, sleep_fn=lambda _: None)
    assert res["ok"] is False
    assert res["after"] == "blocked"
    assert node["health"] == "blocked"
    assert "可能被墙" in res["detail"]
    print("  OK 修复后若仍受阻如实返回真实健康状态（无假绿灯）")


def test_execute_remote_local():
    node = {"name": "本机主控", "host": "127.0.0.1", "local": True}
    captured = []

    def mock_runner(cmd, **kwargs):
        captured.append(cmd)
        return MockCompletedProcess(0)

    repair.execute_remote(node, "echo hello", runner=mock_runner)
    assert captured[0][:2] == ["bash", "-c"]
    print("  OK 本机主控节点直接通过 bash 执行，不走冗余 SSH")


def run_all():
    test_build_commands()
    test_repair_external_node()
    test_repair_linux_success()
    test_repair_windows_success()
    test_repair_config_error()
    test_repair_verify_failed()
    test_execute_remote_local()
    print("通过 7 项")


if __name__ == "__main__":
    run_all()
