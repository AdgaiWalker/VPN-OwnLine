"""Automated regression and contract tests for Cloudflare WARP Clean Egress API."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin
from nodekit.node_manager import NodeManagerError, NodeNotFoundError, NodeValidationError


class WarpApiTests(unittest.TestCase):
    def test_post_warp_toggle_success(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {"Host": "v.example.com"}
        handler.path = "/api/node/warp/toggle"

        payload = {"name": "us-exit", "enabled": True}

        with patch.object(
            admin.node_manager,
            "toggle_warp",
            return_value={"ok": True, "name": "us-exit", "warp_enabled": True, "message": "WARP enabled"}
        ) as mock_toggle:
            with patch("nodekit.http_utils.parse_json_body", return_value=payload):
                admin.H.do_POST(handler)

            self.assertEqual(captured["status"], 200)
            self.assertTrue(captured["data"]["ok"])
            self.assertTrue(captured["data"]["warp_enabled"])
            mock_toggle.assert_called_once_with(name="us-exit", enabled=True)

    def test_post_warp_toggle_dual_path(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {"Host": "v.example.com"}
        handler.path = "/warp/toggle"

        payload = {"name": "sg-exit", "enabled": False}

        with patch.object(
            admin.node_manager,
            "toggle_warp",
            return_value={"ok": True, "name": "sg-exit", "warp_enabled": False, "message": "WARP disabled"}
        ) as mock_toggle:
            with patch("nodekit.http_utils.parse_json_body", return_value=payload):
                admin.H.do_POST(handler)

            self.assertEqual(captured["status"], 200)
            self.assertTrue(captured["data"]["ok"])
            self.assertFalse(captured["data"]["warp_enabled"])
            mock_toggle.assert_called_once_with(name="sg-exit", enabled=False)

    def test_post_warp_toggle_not_found(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {"Host": "v.example.com"}
        handler.path = "/api/node/warp/toggle"

        payload = {"name": "unknown-node", "enabled": True}

        with patch.object(
            admin.node_manager,
            "toggle_warp",
            side_effect=NodeNotFoundError("未找到指定的节点")
        ):
            with patch("nodekit.http_utils.parse_json_body", return_value=payload):
                admin.H.do_POST(handler)

            self.assertEqual(captured["status"], 404)
            self.assertFalse(captured["data"]["ok"])
            self.assertIn("未找到指定的节点", captured["data"]["error"])


if __name__ == "__main__":
    unittest.main()
