"""Hy2Service 单元测试。"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit.hy2_service import Hy2Service


class Hy2ServiceTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            {"name": "美西节点", "type": "vless", "host": "1.2.3.4", "port": 443},
            {"name": "美西节点-HY2", "type": "hysteria2", "host": "1.2.3.4", "port": 8443, "enabled": False},
        ]
        self.mock_logger = MagicMock()
        self.mock_rc = MagicMock()
        self.mock_fw = MagicMock(return_value=("opened", "ok"))

    def test_toggle_missing_params(self):
        code, resp, mutator = Hy2Service.toggle(self.nodes, "", "", True, self.mock_rc, self.mock_fw, self.mock_logger)
        self.assertEqual(code, 400)
        self.assertFalse(resp["ok"])

    def test_toggle_not_found(self):
        code, resp, mutator = Hy2Service.toggle(self.nodes, "9.9.9.9", "不存在", True, self.mock_rc, self.mock_fw, self.mock_logger)
        self.assertEqual(code, 404)
        self.assertFalse(resp["ok"])

    def test_toggle_enable_success(self):
        self.mock_rc.toggle_hy2.return_value = {
            "ok": True,
            "hy2_node": {"name": "美西节点-HY2", "type": "hysteria2", "host": "1.2.3.4", "port": 8443, "enabled": True},
            "verify": {"health": "ok"},
        }
        code, resp, mutator = Hy2Service.toggle(self.nodes, "1.2.3.4", "美西节点", True, self.mock_rc, self.mock_fw, self.mock_logger)
        self.assertEqual(code, 200)
        self.assertTrue(resp["ok"])
        updated = mutator(self.nodes)
        vless = next(n for n in updated if n["name"] == "美西节点")
        hy2 = next(n for n in updated if n["name"] == "美西节点-HY2")
        self.assertTrue(vless["hy2_enabled"])
        self.assertTrue(hy2["enabled"])


if __name__ == "__main__":
    unittest.main()
