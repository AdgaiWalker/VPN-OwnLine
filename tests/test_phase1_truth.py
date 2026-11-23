"""Phase 1 truth & telemetry tests: real proxy probe, isp_leak, alert logging, and /ping route deduplication."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import admin  # noqa: E402
import alert  # noqa: E402
import ipcheck  # noqa: E402
import probe  # noqa: E402


class Phase1TruthTests(unittest.TestCase):
    def test_probe_node_verifies_vless_and_hy2_via_proxy_without_tls_ok(self):
        calls = []

        def fake_proxy(n):
            calls.append(n["name"])
            return {"ok": True, "exit_ip": "168.158.185.30", "ms": 88}

        def fail_tls(*a, **k):
            raise AssertionError("proxy_probe should bypass tls_ok fake greenlight")

        vless_node = {
            "name": "硅谷",
            "host": "43.153.56.137",
            "port": 443,
            "uuid": "u",
            "pbk": "p",
            "sid": "s",
            "isp": {"type": "socks", "server": "168.158.185.30", "server_port": 6297},
        }
        hy2_node = {
            "name": "硅谷-HY2",
            "type": "hysteria2",
            "host": "43.153.56.137",
            "port": 443,
            "password": "pw",
        }
        st_vless = probe.probe_node(vless_node, proxy_probe_fn=fake_proxy, tls_ok_fn=fail_tls)
        st_hy2 = probe.probe_node(hy2_node, proxy_probe_fn=fake_proxy, tls_ok_fn=fail_tls)
        self.assertEqual(calls, ["硅谷", "硅谷-HY2"])
        self.assertTrue(st_vless["ok"])
        self.assertEqual(st_vless["verified_by"], "proxy")
        self.assertEqual(st_vless["exit_ip"], "168.158.185.30")
        self.assertTrue(st_hy2["ok"])
        self.assertEqual(st_hy2["verified_by"], "proxy")

    def test_probe_node_flags_isp_leak_when_exit_equals_vps_host(self):
        vless_node = {
            "name": "硅谷",
            "host": "43.153.56.137",
            "port": 443,
            "uuid": "u",
            "pbk": "p",
            "sid": "s",
            "isp": {"type": "socks", "server": "168.158.185.30", "server_port": 6297},
        }
        st = probe.probe_node(
            vless_node,
            proxy_probe_fn=lambda n: {"ok": True, "exit_ip": "43.153.56.137", "ms": 12},
        )
        self.assertFalse(st["ok"])
        self.assertEqual(st["reason"], "isp_leak")

    def test_probe_node_flags_proxy_when_tcp_open_but_proxy_fails(self):
        vless_node = {
            "name": "硅谷",
            "host": "43.153.56.137",
            "port": 443,
            "uuid": "u",
            "pbk": "p",
            "sid": "s",
        }
        st = probe.probe_node(
            vless_node,
            proxy_probe_fn=lambda n: {"ok": False, "exit_ip": "", "ms": 0},
            tcp_ping_fn=lambda h, p: (True, 3),
        )
        self.assertFalse(st["ok"])
        self.assertEqual(st["reason"], "proxy")
        self.assertEqual(st["verified_by"], "proxy")

    def test_alert_check_and_notify_handles_string_messages(self):
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "alert_state.json")
            status_path = os.path.join(td, "status.json")
            cfg_path = os.path.join(td, "alert.json")
            status_bad = {"硅谷": {"ok": False, "ms": 0, "reason": "proxy"}}
            with (
                patch.object(alert, "STATE_PATH", state_path),
                patch.object(alert, "STATUS_PATH", status_path),
                patch.object(alert, "CFG_PATH", cfg_path),
                patch("nodekit.logger.log") as mock_log,
            ):
                alert.check_and_notify(status_bad)
                msgs = alert.check_and_notify(status_bad)
                self.assertEqual(len(msgs), 1)
                self.assertIn("硅谷", msgs[0])
                mock_log.assert_called()
                args = mock_log.call_args[0]
                self.assertEqual(args[0], "ERROR")
                self.assertEqual(args[1], "ALERT")

    def test_admin_do_get_has_single_ping_branch(self):
        src = (ROOT / "server" / "admin.py").read_text(encoding="utf-8")
        do_get_start = src.index("def do_GET(self):")
        do_post_start = src.index("def do_POST(self):")
        do_get_body = src[do_get_start:do_post_start]
        self.assertEqual(do_get_body.count('norm_path == "/ping"'), 1)

    def test_ipcheck_targets_exit_ip_over_host_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as td:
            nodes_path = os.path.join(td, "nodes.json")
            out_path = os.path.join(td, "iphealth.json")
            nodes = [
                {"name": "硅谷", "host": "43.153.56.137", "exit_ip": "168.158.185.30"},
                {"name": "硅谷-HY2", "host": "43.153.56.137", "exit_ip": "168.158.185.30"},
            ]
            Path(nodes_path).write_text(json.dumps(nodes), encoding="utf-8")
            queried = []

            def fake_query(ip):
                queried.append(ip)
                return {
                    "status": "success",
                    "country": "United States",
                    "city": "Los Angeles",
                    "as": "AS399820 Webshare",
                    "org": "Webshare Residential",
                    "hosting": False,
                    "proxy": False,
                    "mobile": False,
                }

            with (
                patch.object(ipcheck, "NODES", nodes_path),
                patch.object(ipcheck, "OUT", out_path),
                patch.object(ipcheck, "query", side_effect=fake_query),
                patch.object(ipcheck.time, "sleep", lambda s: None),
            ):
                ipcheck.main()

            self.assertEqual(queried, ["168.158.185.30"])
            saved = json.loads(Path(out_path).read_text(encoding="utf-8"))
            self.assertIn("168.158.185.30", saved)
            self.assertEqual(saved["168.158.185.30"]["vps_host"], "43.153.56.137")
            self.assertFalse(saved["168.158.185.30"]["hosting"])


if __name__ == "__main__":
    unittest.main()
