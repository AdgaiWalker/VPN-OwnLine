"""自动化回归测试：验证 NodeManager 与 http_utils 核心逻辑。"""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit import http_utils
from nodekit.node_manager import InMemoryNodeStore, NodeManager


class AdminServicesRegressionTests(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock()
        self.mock_rc = MagicMock()
        self.mock_links = MagicMock()

    def test_http_utils_origin_validation(self):
        handler = MagicMock()
        handler.headers = {"Host": "example.com:8443", "Origin": "https://example.com:8443"}
        self.assertTrue(http_utils.validate_origin(handler))

        handler.headers = {"Host": "example.com:8443", "Origin": "https://evil.com:8443"}
        self.assertFalse(http_utils.validate_origin(handler))

    def test_node_manager_cleanup_workflow(self):
        nodes = [{"name": "node-1", "host": "1.1.1.1", "port": 443, "enabled": True}]
        store = InMemoryNodeStore(nodes)
        mgr = NodeManager(store=store, logger=self.mock_logger)

        # 第一次请求：标记 pending
        resp1 = mgr.remove_node("node-1", cleanup_confirmed=False)
        self.assertTrue(resp1["ok"])
        self.assertTrue(resp1["cleanup_pending"])
        self.assertTrue(store.load()[0]["cleanup_pending"])

        # 第二次请求：确认清理
        resp2 = mgr.remove_node("node-1", cleanup_confirmed=True)
        self.assertTrue(resp2["ok"])
        self.assertFalse(resp2["cleanup_pending"])
        self.assertEqual(len(store.load()), 0)

    def test_node_manager_relay_switch(self):
        nodes = [
            {"name": "hk-relay", "role": "relay", "type": "vless", "host": "1.1.1.1"},
            {"name": "us-exit", "role": "exit", "type": "vless", "host": "2.2.2.2", "exit_country": "US"},
        ]
        store = InMemoryNodeStore(nodes)
        self.mock_rc.switch_relay.return_value = {
            "ok": True,
            "landing": {"host": "2.2.2.2", "port": 443},
            "landing_policy": {"strategy": "fixed"},
            "exit_ip": "2.2.2.2",
            "exit_country": "US",
            "health_detail": "链路畅通",
            "verify": {"health": "ok"},
        }
        mgr = NodeManager(store=store, remote_cfg_mod=self.mock_rc, logger=self.mock_logger)
        resp = mgr.switch_relay("hk-relay", "2.2.2.2")
        self.assertTrue(resp["ok"])
        self.assertEqual(resp["active_target"], "2.2.2.2")

    def test_node_manager_hy2_toggle(self):
        nodes = [
            {"name": "jp-exit", "type": "vless", "host": "3.3.3.3", "port": 443},
            {"name": "jp-exit-HY2", "type": "hysteria2", "host": "3.3.3.3", "port": 8443, "enabled": False},
        ]
        store = InMemoryNodeStore(nodes)
        self.mock_rc.toggle_hy2.return_value = {
            "ok": True,
            "hy2_node": {"name": "jp-exit-HY2", "type": "hysteria2", "host": "3.3.3.3", "port": 8443, "enabled": True},
            "verify": {"health": "ok"},
        }
        mgr = NodeManager(
            store=store,
            remote_cfg_mod=self.mock_rc,
            open_firewall_fn=lambda h, p, proto: ("opened", "ok"),
            logger=self.mock_logger,
        )
        resp = mgr.toggle_hy2(name="jp-exit", host="3.3.3.3", enabled=True)
        self.assertTrue(resp["ok"])
        updated = store.load()
        vless = next(n for n in updated if n["name"] == "jp-exit")
        self.assertTrue(vless["hy2_enabled"])


if __name__ == "__main__":
    unittest.main()
