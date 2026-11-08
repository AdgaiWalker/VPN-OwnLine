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

    def test_evaluate_failover_triggers_when_primary_fails(self):
        nodes = [
            {
                "name": "广州专线",
                "role": "relay",
                "type": "vless",
                "host": "120.79.1.1",
                "landing_primary": "香港主落地",
                "landing_standby": "新加坡备用",
                "landing_active": "2.2.2.2",
                "landing": {"host": "2.2.2.2", "port": 443},
            },
            {"name": "香港主落地", "role": "exit", "type": "vless", "host": "2.2.2.2", "exit_country": "HK"},
            {"name": "新加坡备用", "role": "exit", "type": "vless", "host": "3.3.3.3", "exit_country": "SG"},
        ]
        status = {
            "香港主落地": {"ok": True, "cn_ok": False, "cn_reason": "port"},
            "新加坡备用": {"ok": True, "cn_ok": True, "latency": 60},
        }
        self.mock_rc.switch_relay.return_value = {
            "ok": True,
            "landing": {"host": "3.3.3.3", "port": 443},
            "landing_policy": {"strategy": "fixed"},
            "exit_ip": "3.3.3.3",
            "exit_country": "SG",
            "health_detail": "经新加坡备用落地出网",
            "verify": {"health": "ok"},
        }
        res = RelayService.evaluate_failover(nodes, status, self.mock_rc, self.mock_logger, now_ts=1000)
        relay = next(n for n in res if n["name"] == "广州专线")
        self.assertEqual(relay["landing_active"], "3.3.3.3")
        self.assertEqual(relay["last_failover_ts"], 1000)
        self.assertIn("自愈", relay["failover_reason"])

    def test_evaluate_failover_recovers_to_primary_after_cooldown(self):
        nodes = [
            {
                "name": "广州专线",
                "role": "relay",
                "type": "vless",
                "host": "120.79.1.1",
                "landing_primary": "香港主落地",
                "landing_standby": "新加坡备用",
                "landing_active": "3.3.3.3",
                "landing": {"host": "3.3.3.3", "port": 443},
                "last_failover_ts": 500,
                "failover_policy": {"cooldown_seconds": 300},
            },
            {"name": "香港主落地", "role": "exit", "type": "vless", "host": "2.2.2.2", "exit_country": "HK"},
            {"name": "新加坡备用", "role": "exit", "type": "vless", "host": "3.3.3.3", "exit_country": "SG"},
        ]
        status = {
            "香港主落地": {"ok": True, "cn_ok": True, "latency": 25},
            "新加坡备用": {"ok": True, "cn_ok": True, "latency": 60},
        }
        self.mock_rc.switch_relay.return_value = {
            "ok": True,
            "landing": {"host": "2.2.2.2", "port": 443},
            "landing_policy": {"strategy": "fixed"},
            "exit_ip": "2.2.2.2",
            "exit_country": "HK",
            "health_detail": "经香港主落地出网",
            "verify": {"health": "ok"},
        }
        res = RelayService.evaluate_failover(nodes, status, self.mock_rc, self.mock_logger, now_ts=900)
        relay = next(n for n in res if n["name"] == "广州专线")
        self.assertEqual(relay["landing_active"], "2.2.2.2")
        self.assertNotIn("failover_reason", relay)


if __name__ == "__main__":
    unittest.main()
