"""RelayService 单元测试。"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit.relay_service import RelayService


class RelayServiceTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            {"name": "香港入口", "role": "relay", "type": "vless", "host": "1.1.1.1"},
            {"name": "美西出口", "role": "exit", "type": "vless", "host": "2.2.2.2", "exit_country": "US"},
            {"name": "日本备选", "role": "exit", "type": "vless", "host": "3.3.3.3", "exit_country": "JP"},
        ]
        self.mock_logger = MagicMock()
        self.mock_rc = MagicMock()

    def test_switch_missing_target(self):
        code, resp, mutator = RelayService.switch(self.nodes, "香港入口", "", self.mock_rc, self.mock_logger)
        self.assertEqual(code, 400)
        self.assertFalse(resp["ok"])
        self.assertIsNone(mutator)

    def test_switch_not_found(self):
        code, resp, mutator = RelayService.switch(self.nodes, "不存在的入口", "2.2.2.2", self.mock_rc, self.mock_logger)
        self.assertEqual(code, 404)
        self.assertFalse(resp["ok"])

    def test_switch_success(self):
        self.mock_rc.switch_relay.return_value = {
            "ok": True,
            "landing": {"host": "2.2.2.2", "port": 443},
            "landing_policy": {"strategy": "fixed"},
            "exit_ip": "2.2.2.2",
            "exit_country": "US",
            "health_detail": "直通正常",
            "verify": {"health": "ok"},
        }
        code, resp, mutator = RelayService.switch(self.nodes, "香港入口", "2.2.2.2", self.mock_rc, self.mock_logger)
        self.assertEqual(code, 200)
        self.assertTrue(resp["ok"])
        self.assertIsNotNone(mutator)
        updated = mutator(self.nodes)
        relay = next(n for n in updated if n["name"] == "香港入口")
        self.assertEqual(relay["landing"]["host"], "2.2.2.2")

    def test_unbind_success(self):
        self.mock_rc.unbind_relay.return_value = {"ok": True, "verify": {"health": "ok"}}
        code, resp, mutator = RelayService.unbind(self.nodes, "香港入口", self.mock_rc, self.mock_logger)
        self.assertEqual(code, 200)
        self.assertTrue(resp["ok"])
        self.assertIn("已解除中转关系", resp["message"])
        updated = mutator(self.nodes)
        relay = next(n for n in updated if n["name"] == "香港入口")
        self.assertEqual(relay["role"], "standalone")
        self.assertNotIn("landing", relay)


if __name__ == "__main__":
    unittest.main()
