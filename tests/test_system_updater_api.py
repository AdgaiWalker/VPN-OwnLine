"""Automated tests for System Updater API contracts and dual prefix matching."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin
from nodekit import system_updater


class SystemUpdaterApiTests(unittest.TestCase):
    def setUp(self):
        system_updater.reset_upgrade_state_for_tests()
        with system_updater._CACHE_LOCK:
            system_updater._CACHE["ts"] = 0
            system_updater._CACHE["data"] = None

    def test_version_dual_prefix(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {}

        for endpoint in ("/system/version", "/api/system/version"):
            captured.clear()
            handler.path = endpoint
            admin.H.do_GET(handler)
            self.assertEqual(captured["status"], 200)
            self.assertTrue(captured["data"]["ok"])
            self.assertEqual(captured["data"]["version"], system_updater.CURRENT_VERSION)
            self.assertIn("commit", captured["data"])

    def test_check_update_dual_prefix_and_mock(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {}

        fake_update_info = {
            "ok": True,
            "current_version": "v0.5.0",
            "latest_version": "v0.6.0",
            "has_update": True,
            "changelog": "新版发布说明",
            "published_at": "2026-11-12T00:00:00Z",
            "release_url": "https://github.com/AdgaiWalker/VPN-OwnLine/releases",
            "cached": False,
        }

        with patch.object(admin.updater_mod, "check_update", return_value=fake_update_info) as mock_chk:
            for endpoint in ("/system/check_update?force=1", "/api/system/check_update?force=1"):
                captured.clear()
                handler.path = endpoint
                admin.H.do_GET(handler)
                self.assertEqual(captured["status"], 200)
                self.assertTrue(captured["data"]["ok"])
                self.assertTrue(captured["data"]["has_update"])
                self.assertEqual(captured["data"]["latest_version"], "v0.6.0")

    def test_upgrade_dual_prefix(self):
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler._origin_ok.return_value = True
        handler.headers = {"Content-Type": "application/json", "Content-Length": "2"}
        handler.rfile.read.return_value = b"{}"

        fake_res = {
            "ok": True,
            "status": "upgrading",
            "target_version": "latest",
            "message": "升级任务已在后台启动",
        }

        with patch.object(admin.updater_mod, "trigger_upgrade", return_value=fake_res) as mock_trig:
            for endpoint in ("/system/upgrade", "/api/system/upgrade"):
                captured.clear()
                handler.path = endpoint
                admin.H.do_POST(handler)
                self.assertEqual(captured["status"], 200)
                self.assertEqual(captured["data"]["status"], "upgrading")


if __name__ == "__main__":
    unittest.main()
