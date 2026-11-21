"""自动化回归测试：验证 traffic_stats 核心算法与 /api/traffic/stats 端点契约。"""
import datetime
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit import traffic_stats
import admin


class TrafficStatsApiTests(unittest.TestCase):
    def setUp(self):
        self.mock_usage = {
            "43.153.56.137": {
                "used": 291.5,
                "total": 512.0,
                "start": "2026-10-23",
                "end": "2026-11-23",
                "region": "硅谷",
            },
            "_ts": "2026-11-21T06:00:00Z",
        }
        self.mock_history = {
            "nodes": {
                "43.153.56.137": {
                    "last_seen_used": 291.5,
                    "daily_totals": {
                        "2026-11-20": 4.5,
                        "2026-11-21": 1.2,
                    },
                    "snapshots": [],
                }
            }
        }

    def test_aggregate_all_traffic_stats(self):
        fixed_now = datetime.datetime(2026, 11, 21, 14, 0, 0, tzinfo=datetime.timezone.utc)
        res = traffic_stats.aggregate_all_traffic_stats(self.mock_usage, self.mock_history, now=fixed_now)
        self.assertIn("total", res)
        self.assertIn("nodes", res)
        self.assertEqual(res["total"]["today_gb"], 1.2)
        self.assertEqual(res["total"]["yesterday_gb"], 4.5)
        self.assertEqual(res["total"]["this_month_gb"], 291.5)
        self.assertIn("guidance", res["total"])

        # 检查行动指南生成
        g = res["total"]["guidance"]
        self.assertGreater(g["days_remaining"], 0)
        self.assertGreater(g["remaining_gb"], 0)
        self.assertGreater(g["daily_budget_gb"], 0)
        self.assertIn(g["pace"], ("abundant", "normal", "heavy", "critical"))

    @patch("admin._load_json")
    def test_admin_traffic_stats_dual_prefix(self, mock_load):
        def _fake_load(fname, default=None):
            if fname == "usage.json":
                return self.mock_usage
            if fname == "traffic_history.json":
                return self.mock_history
            return default or {}

        mock_load.side_effect = _fake_load

        # 1. 验证 /traffic/stats
        handler1 = MagicMock()
        handler1.path = "/traffic/stats"
        handler1.headers = {}
        handler1.rfile = io.BytesIO()
        handler1.wfile = io.BytesIO()
        admin.H.do_GET(handler1)
        self.assertTrue(handler1._json.called)
        code1, body1 = handler1._json.call_args[0]
        self.assertEqual(code1, 200)
        self.assertIn("total", body1)

        # 2. 验证 /api/traffic/stats (Caddy 前缀双重匹配)
        handler2 = MagicMock()
        handler2.path = "/api/traffic/stats"
        handler2.headers = {}
        handler2.rfile = io.BytesIO()
        handler2.wfile = io.BytesIO()
        admin.H.do_GET(handler2)
        self.assertTrue(handler2._json.called)
        code2, body2 = handler2._json.call_args[0]
        self.assertEqual(code2, 200)
        self.assertIn("total", body2)


if __name__ == "__main__":
    unittest.main()
