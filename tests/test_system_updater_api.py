"""Automated tests for System Updater API contracts and dual prefix matching."""
import json
import os
import tempfile
import time
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

    def test_failed_child_records_failure_and_allows_retry(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LADDER_DATA": tmp}):
            script = Path(tmp) / "fail.sh"
            script.write_text("#!/bin/sh\nexit 1\n")
            first = system_updater.trigger_upgrade("v9.9.9", script_path=str(script))
            self.assertTrue(first["ok"])
            for _ in range(100):
                status = system_updater.upgrade_status(first["job_id"])
                if status.get("status") == "failed" and not system_updater.is_upgrading():
                    break
                time.sleep(0.02)
            self.assertEqual(status["status"], "failed")
            self.assertFalse(system_updater.is_upgrading())
            self.assertTrue(system_updater.trigger_upgrade("v9.9.9", script_path=str(script))["ok"])

    def test_status_requires_valid_job_id_and_supports_both_prefixes(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LADDER_DATA": tmp}):
            job_id = "a" * 32
            system_updater._write_upgrade_status(job_id, "succeeded", "v1.2.3")
            self.assertFalse(system_updater.upgrade_status("../settings")["ok"])
            for endpoint in ("/system/upgrade-status", "/api/system/upgrade-status"):
                handler = MagicMock()
                handler.path = endpoint + "?id=" + job_id
                handler.headers = {}
                admin.H.do_GET(handler)
                self.assertEqual(handler._json.call_args.args[1]["status"], "succeeded")

    def test_interrupted_systemd_job_does_not_remain_running(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LADDER_DATA": tmp}):
            job_id = "b" * 32
            system_updater._write_upgrade_status(job_id, "running", "v1.2.3")
            path = system_updater._upgrade_status_path(job_id)
            state = json.loads(path.read_text())
            state["started_at"] = 0
            path.write_text(json.dumps(state))
            result = MagicMock(returncode=4, stdout="LoadState=not-found\nActiveState=inactive\n")
            with patch.object(system_updater.sys, "platform", "linux"), patch.object(system_updater.subprocess, "run", return_value=result):
                self.assertEqual(system_updater.upgrade_status(job_id)["status"], "failed")
                result.stdout = "LoadState=loaded\nActiveState=active\n"
                self.assertEqual(system_updater.upgrade_status(job_id)["status"], "running")


if __name__ == "__main__":
    unittest.main()
