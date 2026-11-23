"""Phase 3 tests: declarative reconciliation, reverse_join boundary, and legacy removals."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "scripts"))

import admin  # noqa: E402
import drift as drift_cli  # noqa: E402
from nodekit import join_token, quota_guard, repair, templates  # noqa: E402


class Phase3ConvergenceTests(unittest.TestCase):
    def test_legacy_subconverter_and_patch_remnants_removed(self):
        admin_src = (ROOT / "server/admin.py").read_text(encoding="utf-8")
        for removed in ("subconverter", "_py_patch", "_ps_patch", "patch_remote"):
            self.assertNotIn(removed, admin_src)
            self.assertFalse(hasattr(admin, removed), removed)

        with patch.object(admin, "load_nodes", side_effect=AssertionError("render should be no-op")), \
             patch.object(admin.subprocess, "run", side_effect=AssertionError("render must never reload caddy")):
            self.assertIsNone(admin.render())

        install_src = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
        caddy_example = (ROOT / "deploy/Caddyfile.example").read_text(encoding="utf-8")
        subs_src = (ROOT / "server/nodekit/subscriptions.py").read_text(encoding="utf-8")
        self.assertNotIn("sub_backend", install_src)
        self.assertNotIn("subconverter", caddy_example)
        self.assertNotIn("subconverter", subs_src)

    def test_admin_reconcile_endpoints_and_node_capability_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            data.chmod(0o700)
            nodes = [
                {
                    "name": "硅谷",
                    "host": "198.51.100.10",
                    "port": 443,
                    "uuid": "11111111-1111-4111-8111-111111111111",
                    "sni": "www.apple.com",
                    "sid": "abcd1234",
                    "role": "exit",
                    "source": "builtin",
                    "quota_control_managed": True,
                },
                {
                    "name": "终端接入",
                    "host": "198.51.100.20",
                    "port": 443,
                    "role": "exit",
                    "source": "reverse_join",
                },
                {
                    "name": "Win冻结",
                    "host": "198.51.100.30",
                    "port": 443,
                    "role": "exit",
                    "os": "windows",
                    "source": "builtin",
                },
            ]
            (data / "nodes.json").write_text(json.dumps(nodes, ensure_ascii=False))
            (data / "status.json").write_text("{}")
            (data / "usage.json").write_text("{}")
            (data / "settings.json").write_text(json.dumps({"sub_token": "a" * 32}))

            mock_status = {
                "ok": True,
                "in_sync_count": 0,
                "drifted_count": 1,
                "unmanaged_count": 2,
                "error_count": 0,
                "results": [{"name": "硅谷", "status": "drifted", "diffs": ["outbounds: 现网与期望不一致"], "diff_count": 1}],
            }
            mock_dry = {"ok": True, "name": "硅谷", "status": "drifted", "changed": False, "applied": False, "dry_run": True}
            mock_conv = {"ok": True, "name": "硅谷", "status": "converged", "changed": True, "applied": True, "verify": {"health": "ok", "exit_ip": "198.51.100.10"}}
            mock_unmanaged = {"ok": True, "name": "终端接入", "status": "unmanaged", "changed": False, "applied": False}

            with patch.object(admin, "DATA", str(data)), \
                 patch.object(admin, "NODES", str(data / "nodes.json")), \
                 patch.object(admin, "INITIAL_PASSWORD_MARKER", data / "gate"), \
                 patch.object(admin.reconcile_mod, "inspect_cluster_drift", return_value=mock_status), \
                 patch.object(admin.node_manager, "reconcile_node", side_effect=[mock_dry, mock_conv, mock_unmanaged]) as rec_mock:
                server = admin.HardenedThreadingHTTPServer(("127.0.0.1", 0), admin.H)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    def call(method, path, body=None):
                        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                        headers = {}
                        payload = None
                        if body is not None:
                            payload = json.dumps(body).encode("utf-8")
                            headers["Content-Type"] = "application/json"
                        conn.request(method, path, body=payload, headers=headers)
                        resp = conn.getresponse()
                        data_out = json.loads(resp.read().decode("utf-8"))
                        conn.close()
                        return resp.status, data_out

                    code_n, node_list = call("GET", "/api/nodes")
                    self.assertEqual(code_n, 200)
                    by_name = {n["name"]: n["capability"] for n in node_list}
                    self.assertEqual(by_name["硅谷"]["mode"], "managed")
                    self.assertTrue(by_name["硅谷"]["controllable"])
                    self.assertEqual(by_name["终端接入"]["mode"], "reverse_join")
                    self.assertFalse(by_name["终端接入"]["controllable"])
                    self.assertEqual(by_name["Win冻结"]["mode"], "windows_frozen")
                    self.assertFalse(by_name["Win冻结"]["controllable"])

                    for path in ("/api/reconcile/status", "/reconcile/status"):
                        code_s, st = call("GET", path)
                        self.assertEqual(code_s, 200)
                        self.assertEqual(st["drifted_count"], 1)

                    code_d, res_d = call("POST", "/api/reconcile/apply", {"name": "硅谷"})
                    self.assertEqual(code_d, 200)
                    self.assertTrue(res_d["dry_run"])
                    self.assertEqual(rec_mock.call_args_list[0].kwargs["apply"], False)

                    code_a, res_a = call("POST", "/reconcile/apply", {"name": "硅谷", "dry_run": False})
                    self.assertEqual(code_a, 200)
                    self.assertEqual(res_a["status"], "converged")
                    self.assertEqual(rec_mock.call_args_list[1].kwargs["apply"], True)

                    code_u, _ = call("POST", "/api/reconcile/apply", {"name": "终端接入", "dry_run": False})
                    self.assertEqual(code_u, 409)
                finally:
                    server.shutdown()
                    server.server_close()

    def test_reverse_join_install_script_uses_least_privilege_unit(self):
        script = join_token.generate_install_script(token="ab" * 32, server_url="https://panel.example:8443", role="exit")
        self.assertIn("User=sing-box", script)
        self.assertIn("ProtectSystem=strict", script)
        self.assertIn("CAP_NET_BIND_SERVICE", script)
        self.assertIn("chmod 640 /opt/sing-box/config.json", script)
        for forbidden in ("CAP_SYS_PTRACE", "CAP_DAC_READ_SEARCH", "CAP_NET_ADMIN"):
            self.assertNotIn(forbidden, script)

    def test_reverse_join_and_windows_refuse_repair_and_quota_control(self):
        rj = {"name": "终端节点", "host": "198.51.100.40", "source": "reverse_join", "quota_control_managed": True, "health": "proxy"}
        win = {"name": "Win节点", "host": "198.51.100.41", "os": "windows", "quota_control_managed": True, "health": "proxy"}
        for node in (rj, win):
            self.assertFalse(quota_guard.supports_quota_control(node))
            res = repair.repair_node(node, runner=lambda *a, **kw: self.fail("must not execute remote command"))
            self.assertFalse(res["ok"])
            self.assertTrue(res["requires_manual"])

    def test_drift_render_from_live_roundtrips_isp_hy2_doh_zero_diff(self):
        cfg = templates.exit_config(
            port=443,
            uuid="11111111-1111-4111-8111-111111111111",
            sni="www.apple.com",
            private_key="PRIVKEY_TEST",
            sid="abcd1234",
            hy2={"port": 443, "password": "pw", "obfs_password": "obfs", "sni": "www.apple.com"},
            isp={"type": "socks", "server": "198.51.100.90", "server_port": 6297, "username": "u", "password": "p"},
        )
        want = drift_cli.render_from_live(cfg)
        self.assertEqual(drift_cli.diff(cfg, want), [])


if __name__ == "__main__":
    unittest.main()
