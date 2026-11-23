"""Phase 2 security, stealth gateway, sandboxing, and certificate regression tests."""
import http.client
import importlib.util
import io
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import admin  # noqa: E402
from nodekit import http_utils, maintenance, remote_config  # noqa: E402

RESET_SPEC = importlib.util.spec_from_file_location("reset_admin_password", ROOT / "server/reset_admin_password.py")
reset_tool = importlib.util.module_from_spec(RESET_SPEC)
RESET_SPEC.loader.exec_module(reset_tool)

HASH = "$2b$14$" + "a" * 53


def _render_stealth_caddyfile(*, tls_internal=True, managed_v1=True, proxied_pubjson=True, username="dora"):
    script = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    raw = script.split('cat > "$CADDY_STAGED" << CADDYEOF\n', 1)[1].split("\nCADDYEOF", 1)[0]
    raw = (
        raw.replace("$SETUP_JOB", "phase2")
        .replace("$PASS_HASH", HASH)
        .replace("${DOMAIN}", "v.example.test")
        .replace("$TLS_DIRECTIVE", "tls internal" if tls_internal else "")
        .replace("admin " + HASH, f"{username} {HASH}")
    )
    if not managed_v1:
        raw = raw.replace("# ownline-managed-password-v1\n", "")
        raw = re.sub(r"\n\thandle /change-password \{.*?\n\t\}\n", "\n", raw, flags=re.S)
        raw = re.sub(r"\n\thandle /api/password/\* \{.*?\n\t\}\n", "\n", raw, flags=re.S)
        raw = re.sub(r"\n\t\tforward_auth 127\.0\.0\.1:8099 \{\n\t\t\turi /password-gate\n\t\t\}", "", raw)
    if not proxied_pubjson:
        raw = raw.replace(
            'header Cache-Control "no-store"\n\t\treverse_proxy 127.0.0.1:8099',
            'header Cache-Control "no-store"\n\t\troot * /opt/web-data\n\t\tfile_server',
        )
    return raw + "\n"


def _render_legacy_caddyfile(*, tls_internal=False, managed_v1=True):
    stealth = _render_stealth_caddyfile(tls_internal=tls_internal, managed_v1=managed_v1, proxied_pubjson=True, username="admin")
    legacy = re.sub(r"(?ms)^# ownline-managed-password-v1\n\{\n.*?\n\}\n\n", "# ownline-managed-password-v1\n", stealth)
    legacy = re.sub(
        r"\(app\) \{\n\theader -Server\n\theader X-Content-Type-Options \"nosniff\"\n\theader X-Frame-Options \"DENY\"\n\theader Referrer-Policy \"no-referrer\"\n\n",
        "(app) {\n",
        legacy,
    )
    legacy = legacy.replace(
        "https://v.example.test:8443 {",
        ":80 {\n\tredir https://v.example.test:8443{uri} 308\n}\n\nhttps://v.example.test:8443 {",
    )
    return legacy


class Phase2SecurityTests(unittest.TestCase):
    def test_caddyfile_example_is_stealth_and_no_port_80(self):
        raw = (ROOT / "deploy/Caddyfile.example").read_text(encoding="utf-8")
        for needle in (
            "auto_https disable_redirects",
            "protocols h1 h2",
            "header -Server",
            'header X-Content-Type-Options "nosniff"',
            'header X-Frame-Options "DENY"',
            'header Referrer-Policy "no-referrer"',
            "reverse_proxy 127.0.0.1:8099",
        ):
            self.assertIn(needle, raw)
        self.assertNotIn(":80 {", raw)
        self.assertNotIn("root * /opt/web-data", raw)

    def test_install_script_has_stealth_template_and_least_privilege_users(self):
        script = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
        self.assertNotIn(":80 {", script)
        for needle in (
            "auto_https disable_redirects",
            "protocols h1 h2",
            "header -Server",
            "useradd --system --gid sing-box",
            "chown root:caddy",
            "chmod 640",
        ):
            self.assertIn(needle, script)

    def test_inspect_credentials_supports_stealth_and_legacy_strictly(self):
        for tls_internal in (True, False):
            for managed_v1 in (True, False):
                for proxied in (True, False):
                    cfg = _render_stealth_caddyfile(
                        tls_internal=tls_internal,
                        managed_v1=managed_v1,
                        proxied_pubjson=proxied,
                        username="dora",
                    )
                    domain, user, h = reset_tool.inspect_credentials(cfg)
                    self.assertEqual((domain, user, h), ("v.example.test", "dora", HASH))

        legacy = _render_legacy_caddyfile(tls_internal=True, managed_v1=True)
        self.assertEqual(reset_tool.inspect_credentials(legacy), ("v.example.test", "admin", HASH))

        bad_missing_header = _render_stealth_caddyfile().replace('\theader X-Frame-Options "DENY"\n', "")
        bad_mixed_port80 = _render_stealth_caddyfile().replace(
            "https://v.example.test:8443 {",
            ":80 {\n\tredir https://v.example.test:8443{uri} 308\n}\n\nhttps://v.example.test:8443 {",
        )
        bad_extra_site = _render_stealth_caddyfile() + "\nevil.example {\n\trespond 200\n}\n"
        for bad in (bad_missing_header, bad_mixed_port80, bad_extra_site):
            with self.assertRaises(ValueError):
                reset_tool.inspect_credentials(bad)

    def test_http_utils_security_headers_and_client_ip(self):
        headers_sent = {}
        handler = MagicMock()
        handler.send_header = lambda k, v: headers_sent.__setitem__(k, v)
        handler.wfile = io.BytesIO()
        http_utils.send_json(handler, 200, {"ok": True})
        self.assertEqual(headers_sent["Cache-Control"], "no-store")
        self.assertEqual(headers_sent["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers_sent["X-Frame-Options"], "DENY")
        self.assertEqual(headers_sent["Referrer-Policy"], "no-referrer")

        h1 = MagicMock(headers={"CF-Connecting-IP": "203.0.113.5", "X-Forwarded-For": "10.0.0.1, 10.0.0.2"}, client_address=("127.0.0.1", 1234))
        self.assertEqual(http_utils.extract_client_ip(h1), "203.0.113.5")
        h2 = MagicMock(headers={"X-Forwarded-For": "198.51.100.7, 10.0.0.2"}, client_address=("127.0.0.1", 1234))
        self.assertEqual(http_utils.extract_client_ip(h2), "198.51.100.7")
        h3 = MagicMock(headers={}, client_address=("192.0.2.9", 5555))
        self.assertEqual(http_utils.extract_client_ip(h3), "192.0.2.9")

    def test_sliding_window_rate_limiter_allows_blocks_recovers_and_bounds_keys(self):
        limiter = http_utils.SlidingWindowRateLimiter(max_requests=3, window_seconds=10.0, max_keys=4)
        for t in (100.0, 101.0, 102.0):
            self.assertTrue(limiter.allow("1.2.3.4", now=t))
        self.assertFalse(limiter.allow("1.2.3.4", now=103.0))
        self.assertTrue(limiter.allow("5.6.7.8", now=103.0))
        self.assertTrue(limiter.allow("1.2.3.4", now=110.5))

        for i in range(10):
            self.assertTrue(limiter.allow(f"10.0.0.{i}", now=200.0 + i))
        self.assertLessEqual(len(limiter._buckets), 4)

    def test_hardened_http_server_and_public_rate_limit(self):
        self.assertEqual(admin.HardenedThreadingHTTPServer.request_queue_size, 64)
        self.assertTrue(admin.HardenedThreadingHTTPServer.daemon_threads)
        self.assertTrue(admin.HardenedThreadingHTTPServer.allow_reuse_address)

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            data_dir.chmod(0o700)
            (data_dir / "settings.json").write_text(json.dumps({"sub_token": "a" * 32}))
            (data_dir / "nodes.json").write_text("[]")
            limiter = http_utils.SlidingWindowRateLimiter(max_requests=2, window_seconds=60.0)
            with patch.object(admin, "DATA", str(data_dir)), \
                 patch.object(admin, "INITIAL_PASSWORD_MARKER", data_dir / "gate"), \
                 patch.object(admin, "_PUBLIC_RATE_LIMITER", limiter):
                server = admin.HardenedThreadingHTTPServer(("127.0.0.1", 0), admin.H)
                t = threading.Thread(target=server.serve_forever, daemon=True)
                t.start()
                try:
                    def req(method, path, body=None, ip="198.51.100.88"):
                        c = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
                        headers = {"CF-Connecting-IP": ip}
                        if body is not None:
                            headers["Content-Type"] = "application/json"
                        c.request(method, path, body=body, headers=headers)
                        r = c.getresponse()
                        hdrs = dict(r.getheaders())
                        r.read()
                        c.close()
                        return r.status, hdrs

                    self.assertEqual(req("GET", "/s/wrong-token")[0], 404)
                    self.assertEqual(req("GET", "/join/wrong-token")[0], 404)
                    code, hdrs = req("GET", "/s/wrong-token")
                    self.assertEqual(code, 429)
                    self.assertEqual(hdrs.get("X-Frame-Options"), "DENY")
                    self.assertEqual(req("POST", "/join/register", body="{}")[0], 429)
                    self.assertEqual(req("GET", "/s/wrong-token", ip="198.51.100.99")[0], 404)
                    self.assertEqual(req("GET", "/api/ping")[0], 204)

                    limiter.reset()
                    self.assertEqual(req("GET", "/s/wrong-token")[0], 404)

                    # Exhaust concurrency semaphore directly and verify 503 fail-closed response
                    for _ in range(server.max_concurrent_requests):
                        self.assertTrue(server._concurrency_sem.acquire(blocking=False))
                    try:
                        s_client, s_srv = socket.socketpair()
                        try:
                            server.process_request(s_srv, ("127.0.0.1", 9999))
                            resp = s_client.recv(1024)
                            self.assertIn(b"503 Service Unavailable", resp)
                        finally:
                            s_client.close()
                    finally:
                        for _ in range(server.max_concurrent_requests):
                            server._concurrency_sem.release()
                finally:
                    server.shutdown()
                    server.server_close()

    def test_hy2_self_signed_cert_is_one_year_rsa2048_and_apply_script_sets_singbox_group(self):
        crt_pem, key_pem = remote_config.generate_self_signed_cert_pem()
        self.assertIn("BEGIN CERTIFICATE", crt_pem)
        self.assertIn("BEGIN PRIVATE KEY", key_pem)
        with tempfile.TemporaryDirectory() as tmp:
            crt_path = Path(tmp) / "hy2.crt"
            crt_path.write_text(crt_pem, encoding="utf-8")
            out = subprocess.check_output(
                ["openssl", "x509", "-in", str(crt_path), "-noout", "-subject", "-text"],
                text=True,
                timeout=10,
            )
            self.assertIn("CN=www.apple.com", out.replace(" ", ""))
            self.assertIn("Public-Key: (2048 bit)", out)
            dates = subprocess.check_output(
                ["openssl", "x509", "-in", str(crt_path), "-noout", "-dates"],
                text=True,
                timeout=10,
            )
            not_before = re.search(r"notBefore=(.+)", dates).group(1).strip()
            not_after = re.search(r"notAfter=(.+)", dates).group(1).strip()
            from email.utils import parsedate_to_datetime
            days = (parsedate_to_datetime(not_after) - parsedate_to_datetime(not_before)).days
            self.assertGreaterEqual(days, 364)
            self.assertLessEqual(days, 370)

        script = remote_config._build_apply_script(
            json.dumps({"inbounds": [], "outbounds": []}),
            cfg_path="/opt/sing-box/config.json",
            bin_path="/opt/sing-box/sing-box",
            prov_json_text=json.dumps({"node_id": "198.51.100.1", "config_sha256": "a" * 64, "signature": "b" * 64}),
            prov_path="/etc/sing-box/.evergreen-provenance.json",
            expected={"config_sha256": "a" * 64, "manifest_sha256": "c" * 64},
        )
        self.assertIn("chgrp sing-box", script)
        self.assertIn("chmod 640", script)
        self.assertIn("chmod 600", script)

    def test_systemd_units_hardening_and_ownership_compliance(self):
        sb = (ROOT / "deploy/systemd/sing-box.service").read_text(encoding="utf-8")
        caddy = (ROOT / "deploy/systemd/caddy.service").read_text(encoding="utf-8")
        adm = (ROOT / "deploy/systemd/admin.service").read_text(encoding="utf-8")

        self.assertIn("User=sing-box", sb)
        self.assertIn("ConditionPathExists=!/var/lib/ownline/quota-paused", sb)
        self.assertIn("User=caddy", caddy)
        self.assertIn("StateDirectory=ownline", adm)
        self.assertIn("@privileged", sb)
        self.assertIn("@privileged", caddy)
        self.assertNotIn("@privileged", adm)
        for content in (sb, caddy, adm):
            self.assertIn("ProtectSystem=strict", content)
            self.assertIn("NoNewPrivileges=yes", content)

        self.assertTrue(maintenance._owned_unit("caddy.service", caddy))
        self.assertTrue(maintenance._owned_unit("sing-box.service", sb))
        self.assertTrue(maintenance._owned_unit("admin.service", adm))

    def test_cf_origin_lock_script_guards_and_syntax(self):
        path = ROOT / "scripts/ops/cf_origin_lock.sh"
        self.assertTrue(path.is_file())
        self.assertTrue(bool(path.stat().st_mode & stat.S_IXUSR))
        subprocess.run(["/bin/bash", "-n", str(path)], check=True)
        src = path.read_text(encoding="utf-8")
        self.assertIn("OWNLINE-ORIGIN-", src)
        self.assertIn("127.0.0.0/8", src)
        self.assertIn("::1/128", src)
        for port in ("22", "443"):
            res = subprocess.run(["/bin/bash", str(path), "--enable", "--port", port], capture_output=True, text=True)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("Refusing", res.stderr)


if __name__ == "__main__":
    unittest.main()
