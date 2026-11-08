"""自动化回归测试：验证 SubscriptionUserInfo, PortCoordinator, HostTrafficCollector 领域深度契约。"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit.host_traffic import HostTrafficCollector
from nodekit.ports import PortCoordinator
from nodekit.subscriptions import SubscriptionUserInfo


class DomainDeepeningTests(unittest.TestCase):
    def test_subscription_userinfo_format_and_parse(self):
        info = SubscriptionUserInfo(upload=0, download=1073741824, total=5368709120, expire=1700000000)
        formatted = info.format()
        self.assertEqual(formatted, "upload=0; download=1073741824; total=5368709120; expire=1700000000")

        parsed = SubscriptionUserInfo.parse(formatted)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.download, 1073741824)
        self.assertEqual(parsed.total, 5368709120)
        self.assertEqual(parsed.expire, 1700000000)

    def test_subscription_userinfo_parse_invalid(self):
        self.assertIsNone(SubscriptionUserInfo.parse(""))
        self.assertIsNone(SubscriptionUserInfo.parse("not-a-valid-header"))

    def test_port_coordinator_allocate(self):
        node = {"name": "test-linux", "port": "443"}
        res = PortCoordinator.allocate(node, os_type="linux")
        self.assertEqual(res["tcp_port"], 443)
        self.assertTrue(res["is_custom"])

        node_auto = {"name": "win-node"}
        res_win = PortCoordinator.allocate(node_auto, os_type="windows")
        self.assertEqual(res_win["tcp_port"], 8443)
        self.assertTrue(res_win["is_fallback"])

    def test_host_traffic_collector_parse(self):
        sample_proc = (
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
            "    lo: 1000       10    0    0    0     0          0         0     1000       10    0    0    0     0       0          0\n"
            "  eth0: 50000000   5000  0    0    0     0          0         0 150000000   8000  0    0    0     0       0          0\n"
        )
        usage = HostTrafficCollector.parse(sample_proc, quota_limit_gb=100)
        self.assertIsNotNone(usage)
        self.assertEqual(usage["used"], 0.14)
        self.assertEqual(usage["total"], 100)


if __name__ == "__main__":
    unittest.main()
