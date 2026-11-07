#!/usr/bin/env python3
"""流量保护接口的离线 HTTP 验证，不触碰真实服务器。"""
import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import admin
from nodekit import quota_guard


class QuotaAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = self.tmp.name
        nodes = [{"name": "受控服务器", "host": "192.0.2.5", "quota_control_managed": True},
                 {"name": "未确认服务器", "host": "192.0.2.6"}]
        with open(os.path.join(data, "nodes.json"), "w", encoding="utf-8") as f:
            json.dump(nodes, f)
        with open(os.path.join(data, "usage.json"), "w", encoding="utf-8") as f:
            json.dump({"_ts": datetime.now(timezone.utc).isoformat(),
                       "192.0.2.5": {"used": 70, "total": 100}}, f)
        for obj, name, value in ((admin, "DATA", data), (admin, "NODES", os.path.join(data, "nodes.json")),
                                 (quota_guard, "QUOTA_SETTINGS_FILE", os.path.join(data, "quota_settings.json")),
                                 (quota_guard, "QUOTA_STATE_FILE", os.path.join(data, "quota_state.json")),
                                 (admin.logger, "DATA", data), (admin.logger, "LOG_FILE", os.path.join(data, "events.log"))):
            p = patch.object(obj, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), admin.H)
        self.base = "http://127.0.0.1:%s" % self.server.server_port
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self):
        with urlopen(self.base + "/quota/guard") as r:
            return json.load(r)

    def post(self, body, origin=None, path="/quota/settings"):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = Request(self.base + path, data=json.dumps(body).encode(), headers=headers)
        try:
            with urlopen(req) as r:
                return r.status, json.load(r)
        except HTTPError as e:
            try:
                return e.code, json.load(e)
            finally:
                e.close()

    def test_threshold_roundtrip_and_unknown(self):
        first = self.get()
        self.assertEqual(first["watermarks"]["tripped"], 85)
        self.assertEqual(first["guards"][1]["status"], "unknown")
        self.assertFalse(first["guards"][1]["control_supported"])
        self.assertEqual(self.post({"threshold": 65}, self.base)[0], 200)
        result = self.get()
        self.assertEqual(result["watermarks"]["tripped"], 65)
        self.assertEqual(result["guards"][0]["status"], "tripped")
        self.assertEqual(self.post({"threshold": 101}, self.base)[0], 400)
        self.assertEqual(self.get()["watermarks"]["tripped"], 65)

    def test_origin_requires_exact_host(self):
        self.assertEqual(self.post({"threshold": 50}, self.base + ".attacker.test")[0], 403)
        self.assertEqual(self.post({"threshold": 50}, "https://attacker.test/" + self.base)[0], 403)
        self.assertEqual(self.get()["watermarks"]["tripped"], 85)

    def test_restore_requires_rechecking_ownership(self):
        backup = {"nodes": [{"name": "已恢复", "host": "192.0.2.5", "port": 443,
                             "quota_control_managed": True, "source": "builtin"}]}
        code, _ = self.post(backup, self.base, "/restore")
        self.assertEqual(code, 200)
        with open(admin.NODES, encoding="utf-8") as f:
            restored = json.load(f)
        self.assertNotIn("quota_control_managed", restored[0])
        self.assertEqual(restored[0]["host"], "192.0.2.5")
        self.assertFalse(self.get()["guards"][0]["control_supported"])

    def test_repair_request_does_not_touch_unverified_node(self):
        with open(admin.NODES, encoding="utf-8") as f:
            before = f.read()
        with patch.object(admin.repair_mod, "execute_remote", side_effect=AssertionError("unexpected remote operation")):
            code, response = self.post({"name": "受控服务器"}, self.base, "/repair")
        self.assertEqual(code, 200)
        self.assertFalse(response["all_ok"])
        self.assertTrue(response["results"][0]["requires_manual"])
        with open(admin.NODES, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)

    def test_remove_defers_cleanup_and_preserves_record(self):
        before_name = "受控服务器"
        with patch.object(admin.subprocess, "run", side_effect=AssertionError("unexpected remote operation")):
            code, response = self.post({"name": before_name}, self.base, "/removenode")
        self.assertEqual(code, 200)
        self.assertTrue(response["cleanup_pending"])
        with open(admin.NODES, encoding="utf-8") as f:
            nodes = json.load(f)
        node = next(n for n in nodes if n["name"] == before_name)
        self.assertFalse(node["enabled"])
        self.assertTrue(node["cleanup_pending"])
        self.assertEqual(node["host"], "192.0.2.5")
        self.assertNotIn("quota_control_managed", node)
        self.assertFalse(admin.subs_mod.in_subscription(node))
        code, _ = self.post({"name": before_name, "enabled": True}, self.base, "/editnode")
        self.assertEqual(code, 409)
        with patch.object(admin.subprocess, "run", side_effect=AssertionError("unexpected remote operation")):
            code, response = self.post({"name": before_name, "cleanup_confirmed": True}, self.base, "/removenode")
        self.assertEqual(code, 200)
        self.assertTrue(response["confirmed_by_user"])
        with open(admin.NODES, encoding="utf-8") as f:
            self.assertFalse(any(n["name"] == before_name for n in json.load(f)))

    def test_edit_port_or_key_never_patches_unverified_service(self):
        with open(admin.NODES, encoding="utf-8") as f:
            before = f.read()
        with patch.object(admin, "patch_remote", side_effect=AssertionError("unexpected remote edit")):
            for body in ({"name": "受控服务器", "port": 1234}, {"name": "受控服务器", "newkey": True}):
                self.assertEqual(self.post(body, self.base, "/editnode")[0], 409)
        with open(admin.NODES, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)


if __name__ == "__main__":
    unittest.main()
