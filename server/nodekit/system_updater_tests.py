"""Unit tests for system_updater.py (100% offline, zero network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nodekit import system_updater


class SystemUpdaterTests(unittest.TestCase):
    def setUp(self):
        system_updater.reset_upgrade_state_for_tests()
        with system_updater._CACHE_LOCK:
            system_updater._CACHE["ts"] = 0
            system_updater._CACHE["data"] = None

    def test_parse_version_tuple(self):
        self.assertEqual(system_updater.parse_version_tuple("v0.5.0"), (0, 5, 0))
        self.assertEqual(system_updater.parse_version_tuple("0.4.0"), (0, 4, 0))
        self.assertEqual(system_updater.parse_version_tuple("v1.2.3-beta"), (1, 2, 3))
        self.assertEqual(system_updater.parse_version_tuple("invalid"), (0, 0, 0))
        self.assertEqual(system_updater.parse_version_tuple(""), (0, 0, 0))

    def test_is_newer_version(self):
        self.assertTrue(system_updater.is_newer_version("v0.6.0", current="v0.5.0"))
        self.assertTrue(system_updater.is_newer_version("v1.0.0", current="v0.5.0"))
        self.assertFalse(system_updater.is_newer_version("v0.5.0", current="v0.5.0"))
        self.assertFalse(system_updater.is_newer_version("v0.4.9", current="v0.5.0"))

    def test_get_version_info(self):
        info = system_updater.get_version_info()
        self.assertTrue(info["ok"])
        self.assertEqual(info["version"], system_updater.CURRENT_VERSION)
        self.assertIn("commit", info)
        self.assertIn("app", info)

    def test_check_update_has_newer(self):
        def mock_fetcher():
            return {
                "tag_name": "v0.6.0",
                "body": "- 优化自代理重连\n- 增加新协议",
                "published_at": "2026-11-12T00:00:00Z",
                "html_url": "https://github.com/AdgaiWalker/VPN-OwnLine/releases/tag/v0.6.0"
            }

        res = system_updater.check_update(force=True, mock_fetcher=mock_fetcher, current="v0.5.0")
        self.assertTrue(res["ok"])
        self.assertTrue(res["has_update"])
        self.assertEqual(res["latest_version"], "v0.6.0")
        self.assertIn("优化自代理重连", res["changelog"])
        self.assertFalse(res["cached"])

        # Subsequent check without force should hit cache
        res2 = system_updater.check_update(force=False, mock_fetcher=lambda: self.fail("Should not call fetcher"), current="v0.5.0")
        self.assertTrue(res2["ok"])
        self.assertTrue(res2["cached"])

    def test_check_update_already_latest(self):
        def mock_fetcher():
            return {
                "tag_name": "v0.5.0",
                "body": "当前版本发布记录",
            }

        res = system_updater.check_update(force=True, mock_fetcher=mock_fetcher, current="v0.5.0")
        self.assertTrue(res["ok"])
        self.assertFalse(res["has_update"])
        self.assertEqual(res["latest_version"], "v0.5.0")

    def test_check_update_error_handling(self):
        def mock_error():
            raise RuntimeError("DNS timeout")

        res = system_updater.check_update(force=True, mock_fetcher=mock_error, current="v0.5.0")
        self.assertFalse(res["ok"])
        self.assertFalse(res["has_update"])
        self.assertIn("DNS timeout", res["error"])

    def test_trigger_upgrade_with_runner(self):
        recorded = []

        def fake_runner(script, target_version):
            recorded.append((script, target_version))
            return "started"

        res = system_updater.trigger_upgrade(target_version="v0.6.0", runner=fake_runner)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "upgrading")
        self.assertEqual(recorded, [(system_updater.os.path.abspath(system_updater.os.path.join(system_updater.os.path.dirname(system_updater.__file__), "../../deploy/upgrade.sh")), "v0.6.0")])

        # Concurrent upgrade should be locked
        res_dup = system_updater.trigger_upgrade(target_version="v0.6.0", runner=fake_runner)
        self.assertFalse(res_dup["ok"])
        self.assertIn("进行中", res_dup["error"])


if __name__ == "__main__":
    unittest.main()
