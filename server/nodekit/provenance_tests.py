#!/usr/bin/env python3
"""服务独占性加密存证模块单测。"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import provenance  # noqa: E402


def test_sign_and_verify_valid():
    secret = "secret_key_123456"
    config = '{"log": {"level": "info"}}'
    sha = provenance.compute_config_sha256(config)
    manifest = provenance.sign_provenance("node_01", sha, secret, installed_at=1794132000)

    ok, reason = provenance.verify_provenance(manifest, secret)
    assert ok is True
    assert "合法有效" in reason
    print("  OK 存证正常签名与验证通过")


def test_tampered_config_rejected():
    secret = "secret_key_123456"
    manifest = provenance.sign_provenance("node_01", "original_sha", secret)
    manifest["config_sha256"] = "tampered_sha"

    ok, reason = provenance.verify_provenance(manifest, secret)
    assert ok is False
    assert "不匹配" in reason
    print("  OK 篡改配置哈希后签名校验失败拒绝")


def test_tampered_node_id_rejected():
    secret = "secret_key_123456"
    manifest = provenance.sign_provenance("node_01", "sha256", secret)
    manifest["node_id"] = "node_02"

    ok, reason = provenance.verify_provenance(manifest, secret)
    assert ok is False
    assert "不匹配" in reason
    print("  OK 篡改节点标识后签名校验失败拒绝")


def test_wrong_secret_rejected():
    manifest = provenance.sign_provenance("node_01", "sha256", "correct_secret")
    ok, reason = provenance.verify_provenance(manifest, "wrong_secret")
    assert ok is False
    assert "不匹配" in reason
    print("  OK 错误的主控密钥校验失败拒绝")


def test_malformed_manifest_rejected():
    ok, reason = provenance.verify_provenance("not a dict", "secret")
    assert ok is False
    assert "不是有效的 JSON" in reason

    ok, reason = provenance.verify_provenance({"system": "OtherSystem"}, "secret")
    assert ok is False
    assert "系统标识符不匹配" in reason

    ok, reason = provenance.verify_provenance({"system": provenance.SYSTEM_IDENTIFIER}, "secret")
    assert ok is False
    assert "缺失关键字段" in reason
    print("  OK 畸形存证字典安全拦截拒绝")


def test_remote_provenance_read_and_inject():
    node = {"name": "测试节点", "host": "192.0.2.1", "os": "linux"}
    secret = "master_key_xyz"
    captured_commands = []

    class DummyResult:
        def __init__(self, code, out):
            self.returncode = code
            self.stdout = out
            self.stderr = ""

    def fake_execute(n, cmd, **kwargs):
        captured_commands.append(cmd)
        if "cat" in cmd:
            sample_manifest = provenance.sign_provenance("测试节点", "dummy_sha", secret)
            return DummyResult(0, json.dumps(sample_manifest))
        return DummyResult(0, "")

    # 1. 注入存证
    injected = provenance.inject_remote_provenance(node, '{"sample":"cfg"}', secret, fake_execute)
    assert injected is True
    assert any("mkdir -p" in c and ".evergreen-provenance.json" in c for c in captured_commands)

    # 2. 读取存证
    read_manifest = provenance.read_remote_provenance(node, fake_execute)
    assert read_manifest is not None
    assert read_manifest["node_id"] == "测试节点"
    ok, _ = provenance.verify_provenance(read_manifest, secret)
    assert ok is True
    print("  OK 模拟远端存证注入与读取解析成功")


def run_all():
    test_sign_and_verify_valid()
    test_tampered_config_rejected()
    test_tampered_node_id_rejected()
    test_wrong_secret_rejected()
    test_malformed_manifest_rejected()
    test_remote_provenance_read_and_inject()
    print("通过 6 项")


if __name__ == "__main__":
    run_all()
