"""自动化回归测试：验证 NodeService, RelayService, Hy2Service, http_utils 核心逻辑。"""
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit import http_utils
from nodekit.hy2_service import Hy2Service
from nodekit.node_service import NodeService
from nodekit.relay_service import RelayService


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

    def test_node_service_cleanup_workflow(self):
        nodes = [{"name": "node-1", "host": "1.1.1.1", "port": 443}]
        # 第一次请求：标记 pending
        code, resp, mutator = NodeService.remove_node(nodes, "node-1", False, self.mock_logger)
        self.assertEqual(code, 200)
        self.assertTrue(resp["cleanup_pending"])
        nodes = mutator(nodes)

        # 第二次请求：确认清理
        code, resp, mutator = NodeService.remove_node(nodes, "node-1", True, self.mock_logger)
        self.assertEqual(code, 200)
        self.assertFalse(resp["cleanup_pending"])
        nodes = mutator(nodes)
        self.assertEqual(len(nodes), 0)

    def test_relay_service_switch(self):
        nodes = [
            {"name": "hk-relay", "role": "relay", "type": "vless", "host": "1.1.1.1"},
            {"name": "us-exit", "role": "exit", "type": "vless", "host": "2.2.2.2", "exit_country": "US"},
        ]
        self.mock_rc.switch_relay.return_value = {
            "ok": True,
            "landing": {"host": "2.2.2.2", "port": 443},
            "landing_policy": {"strategy": "fixed"},
            "exit_ip": "2.2.2.2",
            "exit_country": "US",
            "health_detail": "链路畅通",
            "verify": {"health": "ok"},
        }
        code, resp, mutator = RelayService.switch(nodes, "hk-relay", "2.2.2.2", self.mock_rc, self.mock_logger)
        self.assertEqual(code, 200)
        self.assertEqual(resp["active_target"], "2.2.2.2")

    def test_hy2_service_toggle(self):
        nodes = [
            {"name": "jp-exit", "type": "vless", "host": "3.3.3.3", "port": 443},
            {"name": "jp-exit-HY2", "type": "hysteria2", "host": "3.3.3.3", "port": 8443, "enabled": False},
        ]
        self.mock_rc.toggle_hy2.return_value = {
            "ok": True,
            "hy2_node": {"name": "jp-exit-HY2", "type": "hysteria2", "host": "3.3.3.3", "port": 8443, "enabled": True},
            "verify": {"health": "ok"},
        }
        code, resp, mutator = Hy2Service.toggle(
            nodes, "3.3.3.3", "jp-exit", True, self.mock_rc, lambda h, p, proto: ("opened", "ok"), self.mock_logger
        )
        self.assertEqual(code, 200)
        self.assertTrue(resp["ok"])
        updated = mutator(nodes)
        vless = next(n for n in updated if n["name"] == "jp-exit")
        self.assertTrue(vless["hy2_enabled"])


if __name__ == "__main__":
    unittest.main()
