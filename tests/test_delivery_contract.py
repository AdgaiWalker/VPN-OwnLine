"""Automated tests for delivery contract and deep link URL generation."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
import admin
from nodekit import links
from nodekit.subscriptions import SubscriptionUserInfo, subscription_userinfo


class DeliveryContractTests(unittest.TestCase):
    def test_build_deep_links_format(self):
        sub_url = "https://43.153.56.137:8443/s/test_token_12345"
        node_name = "香港专线-01"
        res = links.build_deep_links(sub_url, name=node_name)

        self.assertIn("shadowrocket", res)
        self.assertIn("clash", res)

        # Shadowrocket contract: shadowrocket://add/sub://<base64>?title=<encoded_name>
        sr = res["shadowrocket"]
        self.assertTrue(sr.startswith("shadowrocket://add/sub://"))
        self.assertIn("title=%E9%A6%99%E6%B8%AF%E4%B8%93%E7%BA%BF-01", sr)

        # Clash contract: clash://install-config?url=<encoded_url_with_clash>&name=<encoded_name>
        cl = res["clash"]
        self.assertTrue(cl.startswith("clash://install-config?url="))
        self.assertIn("%2Fclash", cl)
        self.assertIn("name=%E9%A6%99%E6%B8%AF%E4%B8%93%E7%BA%BF-01", cl)

    def test_build_deep_links_empty_safety(self):
        res = links.build_deep_links("")
        self.assertEqual(res, {"shadowrocket": "", "clash": ""})

    def test_subscription_userinfo_formatting(self):
        info = SubscriptionUserInfo(
            upload=1024,
            download=204800,
            total=1073741824,
            expire=1794700800,
        )
        formatted = info.format()
        self.assertEqual(formatted, "upload=1024; download=204800; total=1073741824; expire=1794700800")

        parsed = SubscriptionUserInfo.parse(formatted)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.download, 204800)
        self.assertEqual(parsed.total, 1073741824)
        self.assertEqual(parsed.expire, 1794700800)

    def test_admin_job_delivery_payload_schema(self):
        jid = "feedbeef1234"
        delivery_obj = {
            "dashboard_url": "https://43.153.56.137:8443/",
            "username": "admin",
            "temp_password": "test_initial_pwd_123",
            "sub_token": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "direct_sub_url": "https://43.153.56.137:8443/s/a1b2c3d4e5f60718293a4b5c6d7e8f90",
            "deep_links": links.build_deep_links("https://43.153.56.137:8443/s/a1b2c3d4e5f60718293a4b5c6d7e8f90", name="HK-Node"),
        }
        admin.JOBS[jid] = {
            "state": "done",
            "step": 4,
            "stepname": "安装就绪",
            "log": ["done"],
            "delivery": delivery_obj,
        }

        # Mock admin handler to test /api/node/job and /api/job
        handler = MagicMock()
        captured = {}

        def fake_json(status, data):
            captured["status"] = status
            captured["data"] = data

        handler._json = fake_json
        handler.headers = {}

        # 1. Dual prefix test: /node/job and /api/node/job
        handler.path = f"/api/node/job?id={jid}"
        admin.H.do_GET(handler)
        self.assertEqual(captured["status"], 200)
        self.assertIn("delivery", captured["data"])
        self.assertEqual(captured["data"]["delivery"]["dashboard_url"], "https://43.153.56.137:8443/")

        # 2. Dual prefix test: /job and /api/job
        handler.path = f"/api/job?id={jid}"
        admin.H.do_GET(handler)
        self.assertEqual(captured["status"], 200)
        self.assertIn("delivery", captured["data"])
        self.assertEqual(captured["data"]["delivery"]["username"], "admin")
        self.assertIn("shadowrocket", captured["data"]["delivery"]["deep_links"])


if __name__ == "__main__":
    unittest.main()
