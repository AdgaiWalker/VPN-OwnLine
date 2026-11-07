#!/usr/bin/env python3
"""未经独占验证的服务不得执行自愈；测试无需连接真实服务器。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import repair  # noqa: E402


def test_manual_checks_preserve_node():
    for node in (
        {"name": "Linux", "host": "192.0.2.1", "os": "linux", "health": "proxy"},
        {"name": "Windows", "host": "192.0.2.2", "os": "windows", "ssh_user": "Administrator", "health": "blocked"},
        {"name": "旧内置 Linux", "host": "192.0.2.3", "source": "builtin", "quota_control_managed": True, "health": "proxy"},
        {"name": "旧内置 Windows", "host": "192.0.2.4", "source": "builtin", "ssh_user": "Administrator", "quota_control_managed": True, "health": "proxy"},
    ):
        before = dict(node)
        def do_not_execute(*args, **kwargs):
            raise AssertionError("未证明服务独占，不应执行命令或改写节点")
        result = repair.repair_node(node, runner=do_not_execute, verifier=do_not_execute, sleep_fn=do_not_execute)
        assert not result["ok"] and result["requires_manual"]
        assert result["after"] == before["health"] and node == before
        assert "人工检查" in result["detail"] and "未执行停止或重启" in result["detail"]
    print("  OK Linux、Windows 及旧节点未经验证都不停止或重启")


def test_external_no_execution():
    node = {"name": "外部节点", "source": "external", "health": "unknown"}
    def forbidden(*args, **kwargs):
        raise AssertionError("外部节点不应执行")
    result = repair.repair_node(node, runner=forbidden)
    assert not result["ok"] and "外部节点没有 SSH 控制权限" in result["detail"]
    print("  OK 外部节点不执行远程命令")


def test_execute_remote_local():
    captured = []
    class Result:
        returncode = 0
    def runner(cmd, **kwargs):
        captured.append(cmd)
        return Result()
    repair.execute_remote({"name": "本机", "host": "127.0.0.1", "local": True}, "echo hello", runner=runner)
    assert captured[0][:2] == ["bash", "-c"]
    print("  OK 远程执行工具的本机寻址保持不变")


def run_all():
    test_manual_checks_preserve_node()
    test_external_no_execution()
    test_execute_remote_local()
    print("通过 3 项")


if __name__ == "__main__":
    run_all()
