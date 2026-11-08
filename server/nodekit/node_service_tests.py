"""NodeService 单元测试。"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit.node_service import NodeService


class NodeServiceTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            {"name": "节点A", "host": "1.1.1.1", "port": 443, "enabled": True},
            {"name": "节点A-HY2", "host": "1.1.1.1", "port": 8443, "enabled": True},
        ]
        self.mock_logger = MagicMock()
        self.mock_links = MagicMock()
        self.mock_rc = MagicMock()

    def test_remove_node_not_found(self):
        code, resp, mutator = NodeService.remove_node(self.nodes, "未知节点", False, self.mock_logger)
        self.assertEqual(code, 404)
        self.assertFalse(resp["ok"])

    def test_remove_node_mark_pending(self):
        code, resp, mutator = NodeService.remove_node(self.nodes, "节点A", False, self.mock_logger)
        self.assertEqual(code, 200)
        self.assertTrue(resp["cleanup_pending"])
        updated = mutator(self.nodes)
        self.assertTrue(all(n.get("cleanup_pending") for n in updated))

    def test_remove_node_confirmed(self):
        # 先打上 cleanup_pending
        for n in self.nodes:
            n["cleanup_pending"] = True
        code, resp, mutator = NodeService.remove_node(self.nodes, "节点A", True, self.mock_logger)
        self.assertEqual(code, 200)
        self.assertFalse(resp["cleanup_pending"])
        updated = mutator(self.nodes)
        self.assertEqual(len(updated), 0)

    def test_edit_node_reject_remote_port_change(self):
        code, resp, mutator = NodeService.edit_node(
            self.nodes, "节点A", {"port": 10443}, self.mock_links, self.mock_rc, self.mock_logger
        )
        self.assertEqual(code, 409)
        self.assertIn("暂不能修改服务器端口", resp["error"])


if __name__ == "__main__":
    unittest.main()
