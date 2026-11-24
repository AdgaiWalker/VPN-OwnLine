"""Offline tests for non-root sudo provisioning, 80/TCP delivery errors, billing reconcile API, and custom domain binding."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import ssl
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import admin  # noqa: E402
import ownline_cli  # noqa: E402
from nodekit import advise, installations, links, local_setup_runner, quota_guard, system_updater, traffic_stats  # noqa: E402
from nodekit.local_setup_session import LocalSetupSession  # noqa: E402
from nodekit.node_manager import FileNodeStore, NodeManager, NodeValidationError  # noqa: E402
from nodekit.sshcheck import first_check, node_check, transport  # noqa: E402
from nodekit.sshcheck.problem import Problem  # noqa: E402
import reset_admin_password as reset_tool  # noqa: E402


def _caddy_template():
    script = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    body = script.split('cat > "$CADDY_STAGED" << CADDYEOF\n', 1)[1].split("\nCADDYEOF", 1)[0]
    return (
        body.replace("$SETUP_JOB", "jobdom")
        .replace("$PASS_HASH", "$2b$14$" + "a" * 53)
        .replace("${DOMAIN}", "203-0-113-5.sslip.io")
        .replace("$TLS_DIRECTIVE", "")
        + "\n"
    )


class ZeroCliSudoAndDeliveryTests(unittest.TestCase):
    def test_node_check_allows_passwordless_sudo_and_rejects_unprivileged_user(self):
        class FakeSSH:
            def __init__(self, info):
                self.fingerprint = "SHA256:" + "A" * 43
                self.host_key = mock.Mock()
                self.host_key.get_name.return_value = "ssh-ed25519"
                self.host_key.get_base64.return_value = base64.b64encode(b"k").decode()
                self.info = info

            def python(self, command, timeout=20):
                return self.info

            def close(self):
                pass

        base_info = {
            "os": "ubuntu",
            "version": "22.04",
            "architecture": "x86_64",
            "root": False,
            "sudo_nopasswd": True,
            "systemd": True,
            "existing_singbox": False,
            "singbox_service": "inactive",
            "machine_id": "a" * 32,
        }
        target = {"host": "fixture.example", "address": "8.8.8.8", "ssh_port": 22, "username": "ubuntu"}
        with mock.patch.object(node_check, "normalize", return_value=target), \
             mock.patch.object(node_check, "credentials", return_value={"password": "p"}), \
             mock.patch.object(node_check, "SSH", return_value=FakeSSH(dict(base_info))):
            res = node_check.check({})
            self.assertTrue(res["ready_for_install"])
            self.assertTrue(res["sudo_nopasswd"])
            self.assertTrue(res["privileged"])

        no_sudo = dict(base_info, sudo_nopasswd=False)
        with mock.patch.object(node_check, "normalize", return_value=target), \
             mock.patch.object(node_check, "credentials", return_value={"password": "p"}), \
             mock.patch.object(node_check, "SSH", return_value=FakeSSH(no_sudo)):
            res2 = node_check.check({})
            self.assertFalse(res2["ready_for_install"])
            self.assertFalse(res2["privileged"])
            self.assertIn("ubuntu", res2["message"])

        bad_probe = dict(base_info, sudo_nopasswd="yes")
        with mock.patch.object(node_check, "normalize", return_value=target), \
             mock.patch.object(node_check, "credentials", return_value={"password": "p"}), \
             mock.patch.object(node_check, "SSH", return_value=FakeSSH(bad_probe)):
            with self.assertRaises(Problem):
                node_check.check({})

    def test_first_check_uses_sudo_when_non_root_user_has_nopasswd_sudo(self):
        calls = []

        class FakeSSH:
            fingerprint = "SHA256:checked"

            def __init__(self, target, secret):
                pass

            def python(self, source, payload=None, timeout=20, sudo=False):
                calls.append(sudo)
                return {"machine_id": "a" * 32, "existing_controller": False, "disk_ok": True}

            def close(self):
                pass

        res = {
            "ready_for_install": True,
            "address": "8.8.8.8",
            "fingerprint": "SHA256:checked",
            "machine_id": "a" * 32,
            "root": False,
            "sudo_nopasswd": True,
        }
        with mock.patch.object(first_check.node_check, "check", return_value=res), \
             mock.patch.object(first_check, "normalize", return_value={}), \
             mock.patch.object(first_check, "credentials", return_value={}), \
             mock.patch.object(first_check, "SSH", FakeSSH):
            checked = first_check.check({"username": "ubuntu"})
            self.assertTrue(checked["ready_for_install"])
            self.assertEqual(calls, [True])

    def test_local_setup_runner_wraps_non_root_commands_with_sudo_n(self):
        commands = []
        python_sudo = []

        class FakeSSH:
            def __init__(self, *args):
                pass

            def run(self, command, data=b"", **kwargs):
                commands.append(command)
                if kwargs.get("on_stdout"):
                    kwargs["on_stdout"](b"__OWNLINE_STAGE_V1__:gateway\n")
                return 0, b"", b""

            def python(self, source, payload=None, timeout=180, sudo=False):
                python_sudo.append(sudo)
                return {"ok": True}

            def close(self):
                pass

        checked = {
            "login": {"username": "ubuntu", "password": "secret-should-not-leak"},
            "identity": ("8.8.8.8", "", "a" * 32),
        }
        with mock.patch.object(local_setup_runner, "SSH", FakeSSH), \
             mock.patch.object(local_setup_runner, "normalize", return_value={}), \
             mock.patch.object(local_setup_runner, "credentials", return_value={}), \
             mock.patch.object(local_setup_runner, "emit_bundle", side_effect=lambda p, o: o.write(b"x")), \
             mock.patch.object(local_setup_runner, "verify_delivery", return_value={"dashboard_url": "https://x"}):
            res = local_setup_runner.install(checked, Path("/source"))
            self.assertTrue(res["verified"])
        self.assertTrue(commands[0].startswith("sudo -n bash -c "))
        self.assertIn("sudo -n bash -c ", commands[2])
        self.assertIn("sudo -n rmdir /run/ownline-local-install.lock", commands[-1])
        self.assertEqual(python_sudo, [True])
        self.assertTrue(all("secret-should-not-leak" not in cmd for cmd in commands))

    def test_verify_delivery_and_session_map_80_tcp_and_8443_errors_safely(self):
        with self.assertRaises(installations.InstallError) as tls_err:
            installations.verify_delivery(
                {"domain": "8-8-8-8.sslip.io", "sub_token": "a" * 64},
                "8.8.8.8",
                "pw",
                lambda *_: (_ for _ in ()).throw(ssl.SSLError("secret-ssl-detail")),
                attempts=1,
            )
        self.assertEqual(tls_err.exception.code, "DELIVERY_TLS_CERT")
        self.assertIn("80/TCP", str(tls_err.exception))

        key = b"k"
        ok_res = {
            "ready_for_install": True,
            "address": "8.8.8.8",
            "username": "ubuntu",
            "ssh_port": 22,
            "machine_id": "a" * 32,
            "host_key_type": "ssh-ed25519",
            "host_key": base64.b64encode(key).decode(),
            "fingerprint": "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("="),
        }

        def fail_tls(_checked, report):
            report("delivery_verify")
            raise installations.InstallError("raw-secret-must-not-appear", code="DELIVERY_TLS_CERT")

        session = LocalSetupSession(lambda _: ok_res, fail_tls)
        token = session.check({"host": "8.8.8.8", "password": "pw"})["check_token"]
        session.start(token)
        for _ in range(100):
            st = session.status()
            if st["state"] != "running":
                break
        self.assertEqual(st["state"], "attention")
        self.assertEqual(st["error_code"], "DELIVERY_TLS_CERT")
        self.assertIn("80/TCP", st["message"])
        self.assertNotIn("raw-secret-must-not-appear", st["message"])


class ZeroCliWebOpsAndWorkflowTests(unittest.TestCase):
    def test_quota_reconcile_api_dual_prefix_and_validation(self):
        for prefix in ("", "/api"):
            captured = []
            handler = mock.MagicMock()
            handler.path = prefix + "/quota/reconcile"
            handler.headers = {"Content-Type": "application/json", "Content-Length": "48"}
            handler._json = lambda code, body: captured.append((code, body))

            usage = {"43.153.56.137": {"used": 100.0, "total": 500.0, "end": "2026-11-23"}}
            history = {"43.153.56.137": {}}
            with mock.patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-marker")), \
                 mock.patch.object(admin.http_utils, "validate_origin", return_value=True), \
                 mock.patch.object(admin.http_utils, "parse_json_body", return_value=(200, {"official_gb": 102.0, "official_reset_day": 23})), \
                 mock.patch.object(admin, "_load_json", side_effect=[usage, history]), \
                 mock.patch.object(admin, "load_nodes", return_value=[{"name": "N1", "host": "43.153.56.137", "role": "exit"}]):
                admin.H.do_POST(handler)
            self.assertEqual(captured[0][0], 200)
            self.assertEqual(captured[0][1]["status"], "aligned")
            self.assertTrue(captured[0][1]["reset_day_match"])
            self.assertEqual(quota_guard.reconcile_billing(100.0, 102.0)["status"], "aligned")

        # Invalid negative value rejected
        bad_out = []
        bad_handler = mock.MagicMock()
        bad_handler.path = "/api/quota/reconcile"
        bad_handler._json = lambda code, body: bad_out.append((code, body))
        with mock.patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-marker")), \
             mock.patch.object(admin.http_utils, "validate_origin", return_value=True), \
             mock.patch.object(admin.http_utils, "parse_json_body", return_value=(200, {"official_gb": -5})), \
             mock.patch.object(admin, "_load_json", side_effect=[{}, {}]), \
             mock.patch.object(admin, "load_nodes", return_value=[]):
            admin.H.do_POST(bad_handler)
        self.assertEqual(bad_out[0][0], 400)

    def test_change_domain_validation_dns_rollback_and_admin_api(self):
        with self.assertRaises(ValueError):
            reset_tool.validate_custom_domain("1.2.3.4")
        with self.assertRaises(ValueError):
            reset_tool.validate_custom_domain("bad domain!")

        raw = _caddy_template()
        old_dom, updated = reset_tool.replace_domain(raw, "vpn.example.org")
        self.assertEqual(old_dom, "203-0-113-5.sslip.io")
        self.assertIn("https://vpn.example.org:8443 {", updated)
        self.assertEqual(reset_tool.inspect_credentials(updated)[0], "vpn.example.org")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            caddyfile = td_path / "Caddyfile"
            settings = td_path / "settings.json"
            lockfile = td_path / "reset.lock"
            qr_file = td_path / "qr.png"
            caddyfile.write_text(raw, encoding="utf-8")
            settings.write_text(json.dumps({"domain": "203-0-113-5.sslip.io", "sub_token": "b" * 64, "sub_port": 8443}), encoding="utf-8")

            # DNS mismatch aborts before touching Caddyfile
            with self.assertRaisesRegex(ValueError, "尚未指向当前服务器"):
                reset_tool.change_domain(
                    caddyfile,
                    "vpn.example.org",
                    settings_path=settings,
                    lock_path=lockfile,
                    public_ip_fn=lambda: "203.0.113.5",
                    resolve_ip_fn=lambda _: "198.51.100.99",
                )

            real_lstat = Path.lstat

            def root_stat(p):
                actual = real_lstat(p)
                return types.SimpleNamespace(**{k: (0 if k == "st_uid" else getattr(actual, k)) for k in (
                    "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_mtime_ns"
                )})

            with mock.patch.object(Path, "lstat", root_stat), mock.patch.object(reset_tool.os, "chown"):
                # Success when DNS matches
                out = reset_tool.change_domain(
                    caddyfile,
                    "vpn.example.org",
                    settings_path=settings,
                    qr_out=qr_file,
                    lock_path=lockfile,
                    public_ip_fn=lambda: "203.0.113.5",
                    resolve_ip_fn=lambda _: "203.0.113.5",
                    runner=lambda *a, **k: types.SimpleNamespace(returncode=0),
                )
                self.assertEqual(out["domain"], "vpn.example.org")
                self.assertEqual(out["dashboard_url"], "https://vpn.example.org:8443/")
                self.assertEqual(json.loads(settings.read_text(encoding="utf-8"))["domain"], "vpn.example.org")

                # Rollback on first caddy reload failure (rollback reload succeeds)
                caddyfile.write_text(raw, encoding="utf-8")
                seen_cmds = []

                def fake_runner_rollback_ok(args, **k):
                    seen_cmds.append(list(args))
                    if "reload" in args and len([c for c in seen_cmds if "reload" in c]) == 1:
                        return types.SimpleNamespace(returncode=1)
                    return types.SimpleNamespace(returncode=0)

                with mock.patch.object(reset_tool, "_update_settings_domain") as upd:
                    with self.assertRaisesRegex(RuntimeError, "已自动恢复原配置"):
                        reset_tool.change_domain(
                            caddyfile,
                            "vpn.example.org",
                            settings_path=settings,
                            lock_path=lockfile,
                            skip_dns_check=True,
                            runner=fake_runner_rollback_ok,
                        )
                    upd.assert_not_called()
                self.assertEqual(caddyfile.read_text(encoding="utf-8"), raw)

                # Rollback reload failure also fails loudly and keeps original file restored
                caddyfile.write_text(raw, encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "Caddy 重载失败"):
                    reset_tool.change_domain(
                        caddyfile,
                        "vpn.example.org",
                        settings_path=settings,
                        lock_path=lockfile,
                        skip_dns_check=True,
                        runner=lambda args, **k: types.SimpleNamespace(returncode=1 if "reload" in args else 0),
                    )
                self.assertEqual(caddyfile.read_text(encoding="utf-8"), raw)

        # Dual-prefix /domain/change in admin.py + initial password marker gate
        for prefix in ("", "/api"):
            captured = []
            handler = mock.MagicMock()
            handler.path = prefix + "/domain/change"
            handler._json = lambda code, body: captured.append((code, body))
            with mock.patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-marker")), \
                 mock.patch.object(admin.http_utils, "validate_origin", return_value=True), \
                 mock.patch.object(admin.http_utils, "parse_json_body", return_value=(200, {"domain": "vpn.example.org", "skip_dns_check": True})), \
                 mock.patch.object(admin.password_mod, "change_domain", return_value={"domain": "vpn.example.org", "dashboard_url": "https://vpn.example.org:8443/"}):
                admin.H.do_POST(handler)
            self.assertEqual(captured[0][0], 200)
            self.assertEqual(captured[0][1]["domain"], "vpn.example.org")

    def test_addnode_sh_uses_rsh_root_and_external_probe_workflow_is_node24_clean(self):
        addnode_src = (ROOT / "server/addnode.sh").read_text(encoding="utf-8")
        self.assertIn("rsh_root()", addnode_src)
        self.assertIn('rsh_root "mkdir /run/ownline-node-install.lock"', addnode_src)
        self.assertIn("rsh_root \"python3 '$SOURCE_DIR/server/bootstrap_target.py'\"", addnode_src)

        wf_text = (ROOT / ".github/workflows/external-probe.yml").read_text(encoding="utf-8")
        self.assertIn("actions/checkout@v7", wf_text)
        self.assertIn("actions/setup-python@v7", wf_text)
        self.assertIn("actions/cache@v6", wf_text)
        self.assertIn("scripts/ops/external_probe.py", wf_text)
        self.assertNotIn("@v4", wf_text)
        self.assertNotIn("@v5", wf_text)

    def test_v091_blind_test_regressions(self):
        # P0-2: curl --proxy-user / -U preserved by links.parse_isp_proxy
        parsed_curl = links.parse_isp_proxy(
            "curl --proxy http://198.51.100.22:8080 --proxy-user wsuser:wspass123 https://ipv4.webshare.io/"
        )
        self.assertEqual(parsed_curl["type"], "http")
        self.assertEqual(parsed_curl["server"], "198.51.100.22")
        self.assertEqual(parsed_curl["server_port"], 8080)
        self.assertEqual(parsed_curl["username"], "wsuser")
        self.assertEqual(parsed_curl["password"], "wspass123")

        parsed_u = links.parse_isp_proxy("curl -x socks5://198.51.100.22:8080 -U 'u:p:2' https://ipv4.webshare.io/")
        self.assertEqual(parsed_u["username"], "u")
        self.assertEqual(parsed_u["password"], "p:2")

        # P1-5: NodeManager rejects invalid dict ISP server host with spaces
        with tempfile.TemporaryDirectory() as td:
            nodes_path = Path(td) / "nodes.json"
            nodes_path.write_text(json.dumps([{"name": "us-1", "host": "43.153.56.137", "port": 443}]), encoding="utf-8")
            nm = NodeManager(store=FileNodeStore(lambda: str(nodes_path)), links_mod=links)
            with self.assertRaises(NodeValidationError):
                nm.edit_node("us-1", {"isp": {"type": "socks", "server": "hello world", "server_port": 8080}})

        # P0-3: system_updater uses certifi SSLContext & returns sanitized Chinese error
        ctx = system_updater._build_ssl_context()
        self.assertIsInstance(ctx, ssl.SSLContext)
        with mock.patch.object(system_updater.urllib.request, "urlopen", side_effect=ssl.SSLError("CERTIFICATE_VERIFY_FAILED (_ssl.c:1006)")):
            upd = system_updater.check_update(force=True)
        self.assertFalse(upd["ok"])
        self.assertNotIn("CERTIFICATE_VERIFY_FAILED", upd["error"])
        self.assertNotIn("_ssl.c", upd["error"])
        self.assertIn("证书校验失败", upd["error"])
        doc = ownline_cli.run_doctor()
        self.assertTrue(doc["ca_bundle_ready"])

        # P1-2: verify_node updates status.json and advise hides raw "proxy"
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            nodes_file = td_path / "nodes.json"
            status_file = td_path / "status.json"
            nodes_file.write_text(json.dumps([{"name": "relay-hk", "host": "198.51.100.88", "port": 8443, "health": "proxy"}]), encoding="utf-8")
            status_file.write_text(json.dumps({"relay-hk": {"ok": False, "reason": "proxy"}}), encoding="utf-8")
            with mock.patch.object(admin, "DATA", str(td_path)), \
                 mock.patch.object(admin, "NODES", str(nodes_file)), \
                 mock.patch.object(admin.verify_mod, "run", return_value={"health": "ok", "exit_ip": "43.153.56.137", "exit_country": "US", "detail": "ok"}), \
                 mock.patch.object(admin, "render", return_value=None):
                admin.verify_node({"name": "relay-hk"})
            updated_st = json.loads(status_file.read_text(encoding="utf-8"))
            self.assertTrue(updated_st["relay-hk"]["ok"])
            self.assertNotIn("reason", updated_st["relay-hk"])

        adv_proxy = advise.advise({"health": "unknown"}, {"ok": False, "reason": "proxy"})
        self.assertNotIn("proxy", adv_proxy["reason"])
        self.assertIn("代理不通", adv_proxy["reason"])

        # P1-3: relay bottleneck guidance keeps days_remaining + cycle-end notice
        now_dt = traffic_stats.datetime.datetime(2026, 11, 22, 12, 0, tzinfo=traffic_stats.CN_TZ)
        usage_map = {
            "43.153.56.137": {"used": 300.0, "total": 512.0, "start": "2026-10-23", "end": "2026-11-23", "reset_day": 23},
            "198.51.100.88": {"used": 180.0, "total": 200.0, "start": "2026-10-23", "end": "2026-11-23", "reset_day": 23},
        }
        rep = traffic_stats.aggregate_all_traffic_stats(
            usage_map,
            {"nodes": {}},
            active_nodes=[
                {"name": "walker-sv", "host": "43.153.56.137", "role": "exit"},
                {"name": "relay-hk", "host": "198.51.100.88", "role": "relay"},
            ],
            now=now_dt,
        )
        g_text = rep["total"]["guidance"]["text"]
        self.assertIn("离重置还有", g_text)
        self.assertIn("账单周期即将切换", g_text)

        # P1-4: /api/quota/reconcile resolves reset_day (23) before cycle end day (25)
        captured_rec = []
        rec_handler = mock.MagicMock()
        rec_handler.path = "/api/quota/reconcile"
        rec_handler._json = lambda code, body: captured_rec.append((code, body))
        usage_rec = {"43.153.56.137": {"used": 309.49, "total": 512.0, "start": "2026-10-23", "end": "2026-11-25", "reset_day": 23}}
        with mock.patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-marker")), \
             mock.patch.object(admin.http_utils, "validate_origin", return_value=True), \
             mock.patch.object(admin.http_utils, "parse_json_body", return_value=(200, {"official_gb": 309.49, "official_reset_day": 23})), \
             mock.patch.object(admin, "_load_json", side_effect=lambda name, default=None: usage_rec if name == "usage.json" else {}), \
             mock.patch.object(admin, "load_nodes", return_value=[{"name": "sv", "host": "43.153.56.137", "role": "exit", "reset_day": 23}]):
            admin.H.do_POST(rec_handler)
        self.assertEqual(captured_rec[0][0], 200)
        self.assertTrue(captured_rec[0][1]["reset_day_match"])
        self.assertEqual(captured_rec[0][1]["panel_reset_day"], 23)

        # P1-12: transport.normalize returns novice-friendly TARGET_NOT_ALLOWED text
        with self.assertRaises(Problem) as ctx_err:
            transport.normalize({"host": "192.0.2.1", "password": "p"})
        self.assertEqual(ctx_err.exception.code, "TARGET_NOT_ALLOWED")
        self.assertNotIn("隔离测试目标", ctx_err.exception.message)


if __name__ == "__main__":
    unittest.main()
