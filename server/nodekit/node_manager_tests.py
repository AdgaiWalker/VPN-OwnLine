"""NodeManager 核心深模块全离网自动化测试。

基于 InMemoryNodeStore 内存存储适配器，对 NodeManager 进行全生命周期的黑盒契约断言。
测试覆盖：节点增删查改、生命周期约束、专线切流绑定、HY2 极速通道联动、自动触发渲染及领域异常模型。
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit.node_manager import (
    CleanupPendingError,
    FileNodeStore,
    InMemoryNodeStore,
    NodeConflictError,
    NodeManager,
    NodeNotFoundError,
    NodeValidationError,
    RemoteSyncError,
)


class NodeManagerTests(unittest.TestCase):
    def setUp(self):
        self.mock_remote_cfg = MagicMock()
        self.mock_links = MagicMock()
        self.mock_logger = MagicMock()
        self.mock_on_change = MagicMock()
        self.firewall_calls = []

        def _firewall(host, port, proto):
            self.firewall_calls.append((host, port, proto))
            return ("opened", "ok")

        self.mock_firewall = _firewall

        self.initial_nodes = [
            {
                "name": "hk-relay",
                "role": "relay",
                "type": "vless",
                "host": "1.1.1.1",
                "port": 443,
                "enabled": True,
            },
            {
                "name": "us-exit",
                "role": "exit",
                "type": "vless",
                "host": "2.2.2.2",
                "port": 443,
                "enabled": True,
                "exit_country": "US",
            },
            {
                "name": "sg-exit",
                "role": "exit",
                "type": "vless",
                "host": "3.3.3.3",
                "port": 443,
                "enabled": True,
                "exit_country": "SG",
            },
            {
                "name": "sg-exit-HY2",
                "role": "exit",
                "type": "hysteria2",
                "host": "3.3.3.3",
                "port": 8443,
                "enabled": False,
            },
        ]

        self.store = InMemoryNodeStore(self.initial_nodes)
        self.mgr = NodeManager(
            store=self.store,
            remote_cfg_mod=self.mock_remote_cfg,
            links_mod=self.mock_links,
            logger=self.mock_logger,
            open_firewall_fn=self.mock_firewall,
            on_change=self.mock_on_change,
        )

    def test_query_operations(self):
        nodes = self.mgr.list_nodes()
        self.assertEqual(len(nodes), 4)

        relays = self.mgr.list_nodes(filter_fn=lambda n: n.get("role") == "relay")
        self.assertEqual(len(relays), 1)
        self.assertEqual(relays[0]["name"], "hk-relay")

        node = self.mgr.get_node("us-exit")
        self.assertIsNotNone(node)
        self.assertEqual(node["host"], "2.2.2.2")

        self.assertIsNone(self.mgr.get_node("non-existent"))

    def test_remove_node_two_phase_lifecycle(self):
        # 阶段 1：初次移除，转为 pending 状态，移出订阅
        res1 = self.mgr.remove_node("sg-exit", cleanup_confirmed=False)
        self.assertTrue(res1["ok"])
        self.assertTrue(res1["cleanup_pending"])
        self.mock_on_change.assert_called_once()

        # 检查内存存储中主节点与配对 HY2 均已被标记 pending
        vless = self.mgr.get_node("sg-exit")
        hy2 = self.mgr.get_node("sg-exit-HY2")
        self.assertFalse(vless["enabled"])
        self.assertTrue(vless["cleanup_pending"])
        self.assertFalse(hy2["enabled"])
        self.assertTrue(hy2["cleanup_pending"])

        # 待清理状态禁止重新启用
        with self.assertRaises(NodeConflictError):
            self.mgr.edit_node("sg-exit", {"enabled": True})

        # 阶段 2：人工清理确认，物理移除记录
        self.mock_on_change.reset_mock()
        res2 = self.mgr.remove_node("sg-exit", cleanup_confirmed=True)
        self.assertTrue(res2["ok"])
        self.assertTrue(res2["confirmed_by_user"])
        self.mock_on_change.assert_called_once()

        self.assertIsNone(self.mgr.get_node("sg-exit"))
        self.assertIsNone(self.mgr.get_node("sg-exit-HY2"))
        self.assertEqual(len(self.mgr.list_nodes()), 2)

    def test_remove_node_validation(self):
        with self.assertRaises(NodeNotFoundError):
            self.mgr.remove_node("not-found")

        with self.assertRaises(CleanupPendingError):
            # 未标记 pending 直接确认删除应当被拒绝
            self.mgr.remove_node("hk-relay", cleanup_confirmed=True)

    def test_edit_node_success(self):
        res = self.mgr.edit_node("hk-relay", {
            "newname": "hk-relay-renamed",
            "state": "draining",
            "expire_at": "2026-12-31",
        })
        self.assertTrue(res["ok"])
        self.assertEqual(res["target_name"], "hk-relay-renamed")
        self.mock_on_change.assert_called_once()

        updated = self.mgr.get_node("hk-relay-renamed")
        self.assertIsNotNone(updated)
        self.assertEqual(updated["lifecycle"]["state"], "draining")
        self.assertEqual(updated["expire_at"], "2026-12-31")

    def test_edit_node_port_validation(self):
        with self.assertRaises(NodeValidationError):
            self.mgr.edit_node("hk-relay", {"port": 70000})

        with self.assertRaises(NodeValidationError):
            self.mgr.edit_node("hk-relay", {"port": -1})

    def test_edit_node_isp_sync(self):
        self.mock_links.parse_isp_proxy.return_value = {
            "type": "socks",
            "server": "isp.proxy.com",
            "server_port": 1080,
        }
        self.mock_remote_cfg.sync_isp.return_value = {
            "ok": True,
            "exit_ip": "198.51.100.55",
            "exit_country": "US",
            "health_detail": "住宅出网畅通",
        }

        res = self.mgr.edit_node("us-exit", {"isp": "socks5://isp.proxy.com:1080"})
        self.assertTrue(res["ok"])
        self.mock_on_change.assert_called_once()

        updated = self.mgr.get_node("us-exit")
        self.assertEqual(updated["exit_ip"], "198.51.100.55")
        self.assertEqual(updated["health"], "ok")
        self.assertEqual(updated["isp"]["server"], "isp.proxy.com")

    def test_switch_relay(self):
        self.mock_remote_cfg.switch_relay.return_value = {
            "ok": True,
            "landing": {"host": "2.2.2.2", "port": 443},
            "landing_policy": {"strategy": "fixed"},
            "exit_ip": "2.2.2.2",
            "exit_country": "US",
            "health_detail": "链路畅通",
            "verify": {"health": "ok"},
        }

        res = self.mgr.switch_relay("hk-relay", "2.2.2.2")
        self.assertTrue(res["ok"])
        self.assertEqual(res["active_target"], "2.2.2.2")
        self.mock_on_change.assert_called_once()

        relay = self.mgr.get_node("hk-relay")
        self.assertEqual(relay["landing"]["host"], "2.2.2.2")
        self.assertEqual(relay["exit_ip"], "2.2.2.2")
        self.assertEqual(relay["health"], "ok")

    def test_switch_relay_errors(self):
        with self.assertRaises(NodeValidationError):
            self.mgr.switch_relay("hk-relay", "")

        with self.assertRaises(NodeNotFoundError):
            self.mgr.switch_relay("non-existent-relay", "2.2.2.2")

        with self.assertRaises(NodeNotFoundError):
            self.mgr.switch_relay("hk-relay", "99.99.99.99")

        self.mock_remote_cfg.switch_relay.return_value = {
            "ok": False,
            "error": "SSH 连接超时",
        }
        with self.assertRaises(RemoteSyncError):
            self.mgr.switch_relay("hk-relay", "2.2.2.2")

    def test_bind_and_unbind_relay(self):
        self.mock_remote_cfg.bind_relay.return_value = {
            "ok": True,
            "landing": {"host": "3.3.3.3", "port": 443},
            "landing_policy": {"strategy": "dual"},
            "exit_ip": "3.3.3.3",
            "exit_country": "SG",
            "health_detail": "双落地专线就绪",
            "verify": {"health": "ok"},
        }
        res_bind = self.mgr.bind_relay("hk-relay", "3.3.3.3", "2.2.2.2")
        self.assertTrue(res_bind["ok"])
        self.mock_on_change.assert_called_once()

        self.mock_on_change.reset_mock()
        self.mock_remote_cfg.unbind_relay.return_value = {
            "ok": True,
            "health": "ok",
            "health_detail": "国内独立服务器（未绑定中转，不进订阅）",
        }
        res_unbind = self.mgr.unbind_relay("hk-relay")
        self.assertTrue(res_unbind["ok"])
        self.mock_on_change.assert_called_once()

        relay = self.mgr.get_node("hk-relay")
        self.assertEqual(relay["role"], "standalone")
        self.assertNotIn("landing", relay)

    def test_toggle_hy2_enable_and_disable(self):
        self.mock_remote_cfg.toggle_hy2.return_value = {
            "ok": True,
            "hy2_node": {
                "name": "sg-exit-HY2",
                "type": "hysteria2",
                "host": "3.3.3.3",
                "port": 8443,
                "enabled": True,
            },
            "verify": {"health": "ok"},
        }

        res_enable = self.mgr.toggle_hy2(name="sg-exit", enabled=True)
        self.assertTrue(res_enable["ok"])
        self.assertTrue(res_enable["enabled"])
        self.mock_on_change.assert_called_once()
        self.mock_remote_cfg.toggle_hy2.assert_called_once()
        _, kwargs = self.mock_remote_cfg.toggle_hy2.call_args
        self.assertEqual(kwargs.get("open_firewall_fn"), self.mock_firewall)

        vless = self.mgr.get_node("sg-exit")
        hy2 = self.mgr.get_node("sg-exit-HY2")
        self.assertTrue(vless["hy2_enabled"])
        self.assertTrue(hy2["enabled"])

        # 关闭 HY2
        self.mock_on_change.reset_mock()
        self.mock_remote_cfg.toggle_hy2.return_value = {"ok": True, "verify": {"health": "ok"}}
        res_disable = self.mgr.toggle_hy2(name="sg-exit", enabled=False)
        self.assertTrue(res_disable["ok"])
        self.assertFalse(res_disable["enabled"])
        self.mock_on_change.assert_called_once()

        vless = self.mgr.get_node("sg-exit")
        hy2 = self.mgr.get_node("sg-exit-HY2")
        self.assertFalse(vless["hy2_enabled"])
        self.assertFalse(hy2["enabled"])

    def test_arbitrary_update_nodes(self):
        def _add_marker(nodes):
            for n in nodes:
                n["test_marker"] = True
            return nodes

        res = self.mgr.update_nodes(_add_marker)
        self.assertTrue(all(n.get("test_marker") for n in res))
        self.mock_on_change.assert_called_once()


if __name__ == "__main__":
    unittest.main()
