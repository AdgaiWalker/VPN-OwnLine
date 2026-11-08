#!/usr/bin/env python3
"""未经独占验证的服务不得执行自愈；验证独占存证后方可执行安全闭环自愈。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import provenance, repair  # noqa: E402


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


def test_provenance_verified_self_heal_success():
    secret = "test_master_secret_123"
    node = {"name": "香港节点", "host": "192.0.2.10", "port": 443, "health": "bad"}
    cfg_sha = provenance.compute_config_sha256('{"inbounds":[]}')
    manifest = provenance.sign_provenance("香港节点", cfg_sha, secret)

    class DummyRes:
        def __init__(self, code, out):
            self.returncode = code
            self.stdout = out
            self.stderr = ""

    captured_cmds = []

    def fake_exec(n, cmd, **kwargs):
        captured_cmds.append(cmd)
        if ".evergreen-provenance.json" in cmd:
            return DummyRes(0, json.dumps(manifest))
        if "ss -lptn" in cmd:
            return DummyRes(0, 'LISTEN 0 128 *:443 *:* users:(("sing-box",pid=1234,fd=3))')
        if "BIN check" in cmd or "SYNTAX" in cmd:
            return DummyRes(0, "SYNTAX_OK")
        if "systemctl restart sing-box" in cmd:
            return DummyRes(0, "active")
        return DummyRes(0, "")

    def fake_verifier(n):
        return {"health": "ok", "ok": True, "exit_ip": "192.0.2.10", "detail": "探测正常"}

    res = repair.repair_node(
        node,
        execute_remote_fn=fake_exec,
        verifier=fake_verifier,
        sleep_fn=lambda s: None,
        master_secret=secret,
    )
    assert res["ok"] is True
    assert res["after"] == "ok"
    assert "自愈成功" in res["detail"]
    assert any("systemctl restart sing-box" in c for c in captured_cmds)
    print("  OK 持有合法存证且端口正常的节点安全自愈成功并重载")


def test_provenance_port_conflict_safety_abort():
    secret = "test_master_secret_123"
    node = {"name": "东京节点", "host": "192.0.2.20", "port": 443, "health": "bad"}
    cfg_sha = provenance.compute_config_sha256('{"inbounds":[]}')
    manifest = provenance.sign_provenance("东京节点", cfg_sha, secret)

    class DummyRes:
        def __init__(self, code, out):
            self.returncode = code
            self.stdout = out

    restarted = []

    def fake_exec(n, cmd, **kwargs):
        if ".evergreen-provenance.json" in cmd:
            return DummyRes(0, json.dumps(manifest))
        if "ss -lptn" in cmd:
            # 端口被第三方 nginx 占用
            return DummyRes(0, 'LISTEN 0 128 *:443 *:* users:(("nginx",pid=888,fd=4))')
        if "restart" in cmd:
            restarted.append(cmd)
        return DummyRes(0, "")

    res = repair.repair_node(
        node,
        execute_remote_fn=fake_exec,
        master_secret=secret,
    )
    assert res["ok"] is False
    assert res["requires_manual"] is True
    assert "被非 sing-box 进程占用" in res["detail"]
    assert len(restarted) == 0  # 绝对未执行任何重启操作
    print("  OK 目标端口被其他进程占用时安全终止自愈，未误杀外部服务")


def run_all():
    test_manual_checks_preserve_node()
    test_external_no_execution()
    test_execute_remote_local()
    test_provenance_verified_self_heal_success()
    test_provenance_port_conflict_safety_abort()
    print("通过 5 项")


if __name__ == "__main__":
    run_all()
