"""Automated regression and contract tests for Relay Auto-Pair API."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin
from nodekit.node_manager import NodeManagerError, NodeValidationError


class RelayAutoPairApiTests(unittest.TestCase):
    def test_post_auto_pair_relay_success(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {"Host": "v.example.com"}
        handler.path = "/api/relay/auto-pair"

        with patch.object(
            admin.node_manager,
            "auto_pair_relay",
            return_value={"ok": True, "message": "已成功建立中转加速专线"}
        ) as mock_pair:
            with patch("nodekit.http_utils.parse_json_body", return_value={}):
                admin.H.do_POST(handler)

            self.assertEqual(captured["status"], 200)
            self.assertTrue(captured["data"]["ok"])
            mock_pair.assert_called_once()

    def test_post_auto_pair_relay_dual_prefix(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {"Host": "v.example.com"}
        handler.path = "/relay/auto-pair"

        with patch.object(
            admin.node_manager,
            "auto_pair_relay",
            return_value={"ok": True, "message": "已成功建立中转加速专线"}
        ) as mock_pair:
            with patch("nodekit.http_utils.parse_json_body", return_value={}):
                admin.H.do_POST(handler)

            self.assertEqual(captured["status"], 200)
            self.assertTrue(captured["data"]["ok"])
            mock_pair.assert_called_once()


if __name__ == "__main__":
    unittest.main()
