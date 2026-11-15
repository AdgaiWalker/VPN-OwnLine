import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit.ai_feedback import categorize_entry, analyze_feedback_entries


class TestAiFeedback(unittest.TestCase):
    def test_empty_entries(self):
        res = analyze_feedback_entries([])
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_count"], 0)
        self.assertEqual(res["urgency"], "clean")
        self.assertEqual(len(res["clusters"]), 0)

    def test_categorize_port_blocked_by_telemetry(self):
        # User didn't type keywords, but telemetry shows port error
        entry = {
            "message": "不知道怎么回事",
            "type": "bug",
            "diagnostics": {
                "nodes": [
                    {"name": "Guangzhou", "health": "port", "ok": False}
                ]
            }
        }
        cat = categorize_entry(entry)
        self.assertEqual(cat, "port_or_firewall")

    def test_categorize_latency_by_keywords_and_telemetry(self):
        entry = {
            "message": "晚上看油管一直在转圈，很卡",
            "type": "bug",
            "diagnostics": {
                "nodes": [
                    {"name": "SiliconValley", "health": "ok", "ms": 320}
                ]
            }
        }
        cat = categorize_entry(entry)
        self.assertEqual(cat, "latency_or_congestion")

    def test_categorize_client_config(self):
        entry = {
            "message": "小火箭扫码显示格式错误，怎么导入？",
            "type": "bug",
            "diagnostics": {}
        }
        cat = categorize_entry(entry)
        self.assertEqual(cat, "client_config")

    def test_categorize_feature_idea(self):
        entry = {
            "message": "希望能支持多用户流量独立配额",
            "type": "idea",
            "diagnostics": {}
        }
        cat = categorize_entry(entry)
        self.assertEqual(cat, "feature_idea")

    def test_analyze_feedback_clustering_and_actions(self):
        entries = [
            {
                "id": "1",
                "message": "广州机器连不上了",
                "type": "bug",
                "diagnostics": {
                    "nodes": [{"name": "广州", "health": "port", "ok": False}]
                }
            },
            {
                "id": "2",
                "message": "看视频很慢",
                "type": "bug",
                "diagnostics": {
                    "nodes": [{"name": "硅谷", "health": "ok", "ms": 280}]
                }
            },
            {
                "id": "3",
                "message": "希望加个香港节点",
                "type": "idea",
                "diagnostics": {}
            }
        ]
        res = analyze_feedback_entries(entries)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total_count"], 3)
        self.assertEqual(res["urgency"], "high")  # because port blocking exists
        self.assertGreaterEqual(len(res["clusters"]), 3)
        self.assertIn("广州", res["clusters"][0]["affected_nodes"] if res["clusters"][0]["key"] == "port_or_firewall" else res["clusters"][1]["affected_nodes"])
        self.assertTrue(any("高优先级" in item for item in res["action_items"]))


if __name__ == "__main__":
    unittest.main()
