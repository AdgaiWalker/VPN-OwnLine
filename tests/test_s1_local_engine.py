import contextlib
import http.client
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

from server import local_setup, ownline_cli, tencent_discovery
from server.nodekit import installations, local_diag, local_setup_progress
from server.nodekit.local_vault import BlindVault, VaultError
from server.nodekit.sshcheck.problem import Problem

ROOT = Path(__file__).resolve().parents[1]


class _FakeSession:
    def __init__(self, check_fn=None):
        self._check_fn = check_fn or (lambda body: {"result": {"ready_for_install": True, "username": body.get("username", "root"), "address": body.get("host", "198.51.100.2"), "ssh_port": body.get("ssh_port", 22), "os": "debian", "version": "12"}, "check_token": "tok-1"})
        self.seen_checks = []
        self.started_tokens = []

    def status(self):
        return {"state": "idle"}

    def check(self, body):
        self.seen_checks.append(dict(body))
        return self._check_fn(body)

    def start(self, token):
        self.started_tokens.append(token)


class S1LocalDiagTests(unittest.TestCase):
    def test_event_registry_synced_with_markdown_doc(self):
        doc_path = ROOT / "docs" / "02-本地诊断事件表.md"
        self.assertTrue(doc_path.is_file(), "docs/02-本地诊断事件表.md missing")
        self.assertEqual(
            doc_path.read_text(encoding="utf-8"),
            local_diag.render_events_markdown(),
        )

    def test_unregistered_event_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "diag.jsonl"
            with self.assertRaises(ValueError):
                local_diag.emit_event("nonexistent_event", {}, log_path=log_file)

    def test_redaction_strips_all_secret_shapes_and_preserves_safe_metadata(self):
        pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nabcdef123456\n-----END OPENSSH PRIVATE KEY-----"
        secrets_samples = [
            "my-raw-ssh-password-99",
            "Basic dXNlcjpzZWNyZXQ=",
            "s5pass987",
            "webpass456",
            "AKIDTESTSECRETKEY12345",
            "tencent-secret-key-xyz",
            "abcdef123456",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "diag.jsonl"
            local_diag.emit_event(
                "ssh_check_started",
                {
                    "host": "198.51.100.2",
                    "auth_type": "password",
                    "password": "my-raw-ssh-password-99",
                    "private_key": pem,
                    "secret_key": "tencent-secret-key-xyz",
                    "proxy_url": "socks5://webuser:s5pass987@198.51.100.9:1080",
                    "note": "cmd 198.51.100.8:8080:webu:webpass456 auth Basic dXNlcjpzZWNyZXQ= key AKIDTESTSECRETKEY12345",
                },
                log_path=log_file,
            )
            raw = log_file.read_text(encoding="utf-8")
            for leak in secrets_samples:
                self.assertNotIn(leak, raw)
            self.assertIn("[REDACTED]", raw)
            events = local_diag.read_recent_events(log_path=log_file)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["detail"]["host"], "198.51.100.2")
            self.assertEqual(events[0]["detail"]["auth_type"], "password")
            self.assertEqual(events[0]["detail"]["password"], "[REDACTED]")
            self.assertEqual(events[0]["detail"]["secret_key"], "[REDACTED]")


class S1BlindVaultTests(unittest.TestCase):
    def test_all_four_slots_round_trip_without_exposing_secrets_in_metadata(self):
        clock = [100.0]
        events = []
        vault = BlindVault(clock=lambda: clock[0], on_event=lambda e, d: events.append((e, d)))

        samples = [
            ("ssh", {"host": "198.51.100.10", "password": "ssh-secret-value-1"}, "ssh-secret-value-1"),
            ("tencent_api", {"secret_id": "AKIDEXAMPLE123456", "secret_key": "tc-secret-value-2"}, "tc-secret-value-2"),
            ("webshare_isp", {"proxy_url": 'curl --proxy "http://wsuser:ws-secret-pass-3@168.158.185.30:6297"'}, "ws-secret-pass-3"),
            ("panel_auth", {"dashboard_url": "https://198.51.100.10:8443/", "password": "panel-secret-value-4"}, "panel-secret-value-4"),
        ]

        handles = []
        for slot, payload, raw_secret in samples:
            req = vault.create_request(slot, label=f"test-{slot}", target_hint="198.51.100.10")
            self.assertTrue(req["request_id"].startswith("vr_"))
            sub = vault.submit_request(req["request_id"], payload)
            h = sub["handle"]
            handles.append((slot, h, payload, raw_secret))
            self.assertTrue(h.startswith("vh_"))
            st = vault.request_status(req["request_id"])
            desc = vault.describe(h)
            serialized = json.dumps([sub, st, desc], ensure_ascii=False)
            self.assertNotIn(raw_secret, serialized)
            self.assertNotIn("wsuser", serialized)

        # Ensure metadata list contains zero secrets.
        listed = json.dumps(vault.list_handles(), ensure_ascii=False)
        for _, _, raw_secret in samples:
            self.assertNotIn(raw_secret, listed)
        self.assertNotIn("vault_submitted", str(listed))
        self.assertTrue(any(e == "vault_submitted" for e, _ in events))
        self.assertNotIn("ssh-secret-value-1", json.dumps(events, ensure_ascii=False))

        # Slot mismatch fails cleanly.
        with self.assertRaises(VaultError) as ctx:
            vault.borrow(handles[0][1], expected_slot="tencent_api")
        self.assertEqual(ctx.exception.code, "VAULT_SLOT_MISMATCH")

        # Consume deletes and scrubs handle.
        borrowed_tc = vault.borrow(handles[1][1], expected_slot="tencent_api", consume=True)
        self.assertEqual(borrowed_tc["secret_key"], "tc-secret-value-2")
        with self.assertRaises(VaultError):
            vault.borrow(handles[1][1])

        # TTL expiration cleans up remaining handles.
        clock[0] = 800.0
        self.assertEqual(vault.list_handles(), [])
        with self.assertRaises(VaultError):
            vault.borrow(handles[0][1])

    def test_ssh_pem_validation_and_cancel_clear(self):
        vault = BlindVault()
        req = vault.create_request("ssh")
        with self.assertRaises(VaultError):
            vault.submit_request(req["request_id"], {"host": "1.2.3.4", "password": "-----BEGIN OPENSSH PRIVATE KEY-----"})
        pem = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"
        sub = vault.submit_request(req["request_id"], {"host": "1.2.3.4", "private_key": pem, "passphrase": "phrase-9"})
        borrowed = vault.borrow(sub["handle"], expected_slot="ssh")
        self.assertEqual(borrowed["private_key"], pem)
        self.assertEqual(borrowed["passphrase"], "phrase-9")
        self.assertEqual(vault.describe(sub["handle"])["summary"]["auth_type"], "private_key")

        req2 = vault.create_request("ssh")
        cancelled = vault.cancel_request(req2["request_id"])
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(vault.clear(), 1)
        self.assertEqual(vault.list_handles(), [])


class S1HttpAndCliIntegrationTests(unittest.TestCase):
    def _req(self, server, method, path, body=None, with_auth=True):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        headers = {"Host": server.guard.host}
        if with_auth:
            headers["Cookie"] = "ownline_setup=" + server.guard.token
        raw = None
        if body is not None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            if with_auth:
                headers["Origin"] = server.guard.origin
        conn.request(method, path, body=raw, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), data

    def test_vault_http_flow_check_with_fingerprint_tencent_update_and_quit(self):
        with tempfile.TemporaryDirectory() as tmp:
            diag_file = Path(tmp) / "diag.jsonl"
            fp = "SHA256:" + "B" * 43
            attempts = []

            def check_fn(body):
                attempts.append(dict(body))
                if body.get("fingerprint") != fp:
                    raise Problem("HOST_KEY_CONFIRMATION", "需要核对指纹", 409, {"fingerprint": fp})
                return {
                    "result": {
                        "ready_for_install": True,
                        "username": body["username"],
                        "address": body["host"],
                        "ssh_port": body["ssh_port"],
                        "os": "debian",
                        "version": "12",
                    },
                    "check_token": "chk-xyz",
                }

            session = _FakeSession(check_fn=check_fn)
            server = local_setup.create_server(
                session=session,
                diag_log=diag_file,
                update_checker=lambda force=False: {"ok": True, "current_version": "v0.7.0", "latest_version": "v0.7.1", "has_update": True, "force": force},
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                status, headers, body = self._req(server, "GET", "/vault", with_auth=False)
                self.assertEqual(status, 200)
                self.assertIn("HttpOnly", headers["Set-Cookie"])
                self.assertIn(b"slot-ssh", body)

                # Create SSH vault request, submit, then check via handle with fingerprint retry.
                st, _, data = self._req(server, "POST", "/api/vault/request", {"slot": "ssh", "target_hint": "198.51.100.5"})
                self.assertEqual(st, 201)
                req_obj = json.loads(data)
                st, _, sub_data = self._req(
                    server,
                    "POST",
                    "/api/vault/submit",
                    {"request_id": req_obj["request_id"], "payload": {"host": "198.51.100.5", "password": "ssh-top-secret-password"}},
                )
                self.assertEqual(st, 200)
                ssh_handle = json.loads(sub_data)["handle"]

                st, _, c1 = self._req(server, "POST", "/api/check", {"vault_handle": ssh_handle})
                self.assertEqual(st, 409)
                self.assertEqual(json.loads(c1)["fingerprint"], fp)

                st, _, c2 = self._req(server, "POST", "/api/check", {"vault_handle": ssh_handle, "fingerprint": fp})
                self.assertEqual(st, 200)
                self.assertEqual(json.loads(c2)["check_token"], "chk-xyz")
                self.assertEqual(attempts[-1]["password"], "ssh-top-secret-password")

                # Tencent API handle test (mocked cloud API).
                st, _, treq = self._req(server, "POST", "/api/vault/request", {"slot": "tencent_api"})
                st, _, tsub = self._req(
                    server,
                    "POST",
                    "/api/vault/submit",
                    {"request_id": json.loads(treq)["request_id"], "payload": {"secret_id": "AKIDMOCK12345678", "secret_key": "tc-secret-key-888"}},
                )
                tc_handle = json.loads(tsub)["handle"]
                with patch.object(tencent_discovery, "discover_for_local_setup", return_value={"instances": [{"ip": "1.2.3.4"}], "incomplete_regions": []}) as disc:
                    st, _, td = self._req(server, "POST", "/api/tencent/instances", {"vault_handle": tc_handle, "product": "cvm"})
                    self.assertEqual(st, 200)
                    disc.assert_called_once_with("AKIDMOCK12345678", "tc-secret-key-888", product="cvm")

                # Update check & redacted diag events API.
                st, _, upd = self._req(server, "GET", "/api/update?force=1")
                self.assertEqual(st, 200)
                self.assertEqual(json.loads(upd)["latest_version"], "v0.7.1")

                st, _, evs = self._req(server, "GET", "/api/diag/events?limit=20")
                self.assertEqual(st, 200)
                ev_text = evs.decode("utf-8")
                self.assertNotIn("ssh-top-secret-password", ev_text)
                self.assertNotIn("tc-secret-key-888", ev_text)
                self.assertNotIn("AKIDMOCK12345678", ev_text)

                # Quit clears all vault handles.
                st, _, _ = self._req(server, "POST", "/api/quit", {})
                self.assertEqual(st, 200)
                self.assertEqual(server.vault.list_handles(), [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_cli_tty_and_browser_vault_and_doctor_never_leak_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            diag_file = Path(tmp) / "diag.jsonl"
            state_file = Path(tmp) / "agent_state.json"

            session = _FakeSession()
            server = local_setup.create_server(session=session, diag_log=diag_file)
            local_setup._write_state_file(state_file, server)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                # 1. Doctor command JSON
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = ownline_cli.main(["doctor", "--json"], state_path=state_file, diag_log=diag_file)
                self.assertEqual(rc, 0)
                doc = json.loads(out.getvalue())
                self.assertTrue(doc["ok"])
                self.assertTrue(doc["daemon_running"])
                self.assertTrue(all(doc["web_bundles"].values()))

                # 2. TTY fallback vault request never echoes secret to stdout/stderr/diag.
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = ownline_cli.main(
                        ["vault", "request", "--slot", "ssh", "--hint", "198.51.100.77", "--mode", "tty", "--json"],
                        state_path=state_file,
                        diag_log=diag_file,
                        prompt_fn=lambda _: "",
                        secret_prompt_fn=lambda _: "tty-ultra-secret-ssh-pass",
                    )
                self.assertEqual(rc, 0)
                res_tty = json.loads(out.getvalue())
                self.assertTrue(res_tty["ok"])
                self.assertEqual(res_tty["mode"], "tty")
                self.assertTrue(res_tty["handle"].startswith("vh_"))
                self.assertNotIn("tty-ultra-secret-ssh-pass", out.getvalue() + err.getvalue())

                # 3. CLI check via vault handle.
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = ownline_cli.main(
                        ["check", "--vault-handle", res_tty["handle"], "--json"],
                        state_path=state_file,
                        diag_log=diag_file,
                    )
                self.assertEqual(rc, 0)
                chk = json.loads(out.getvalue())
                self.assertEqual(chk["check_token"], "tok-1")
                self.assertNotIn("tty-ultra-secret-ssh-pass", out.getvalue())

                # 4. Browser vault request completed asynchronously by simulated user submission.
                client = ownline_cli.LocalDaemonClient(server.guard.origin, server.guard.token)
                opened_urls = []

                def simulate_browser(url):
                    opened_urls.append(url)
                    req_id = url.split("req=", 1)[1]
                    def submit_worker():
                        client.post_json(
                            "/api/vault/submit",
                            {"request_id": req_id, "payload": {"proxy_url": "198.51.100.88:9000:wsuser:ws-browser-secret-9"}},
                        )
                    threading.Thread(target=submit_worker, daemon=True).start()
                    return True

                with contextlib.redirect_stderr(io.StringIO()):
                    res_browser = ownline_cli.run_vault_request(
                        "webshare_isp",
                        mode="browser",
                        client=client,
                        diag_log=diag_file,
                        open_browser_fn=simulate_browser,
                        poll_interval=0.02,
                    )
                self.assertTrue(res_browser["ok"])
                self.assertEqual(res_browser["mode"], "browser")
                self.assertEqual(res_browser["summary"]["host"], "198.51.100.88")
                self.assertNotIn("ws-browser-secret-9", json.dumps(res_browser, ensure_ascii=False))

                # 5. Logs & Clear commands.
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = ownline_cli.main(["logs", "--limit", "10", "--json"], state_path=state_file, diag_log=diag_file)
                self.assertEqual(rc, 0)
                self.assertNotIn("tty-ultra-secret-ssh-pass", out.getvalue())
                self.assertNotIn("ws-browser-secret-9", out.getvalue())

                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = ownline_cli.main(["vault", "clear", "--json"], state_path=state_file, diag_log=diag_file)
                self.assertEqual(rc, 0)
                self.assertEqual(json.loads(out.getvalue())["cleared"], 2)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_root_ownline_cli_doctor_subprocess_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(
                __import__("os").environ,
                OWNLINE_DIAG_LOG=str(Path(tmp) / "diag.jsonl"),
                OWNLINE_LOCAL_STATE=str(Path(tmp) / "state.json"),
            )
            proc = subprocess.run(
                [sys.executable, str(ROOT / "ownline.py"), "doctor", "--json"],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            data = json.loads(proc.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["version"], "v0.7.0")


class S1CrossPlatformAndPolicyTests(unittest.TestCase):
    def test_emit_bundle_uses_posix_paths_only(self):
        buf = io.BytesIO()
        installations.emit_bundle(ROOT / "server", buf)
        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r:gz") as tf:
            names = tf.getnames()
        self.assertTrue(all("\\" not in n for n in names))
        self.assertIn("server/ownline_cli.py", names)
        self.assertIn("server/nodekit/local_vault.py", names)
        self.assertIn("server/nodekit/local_diag.py", names)

    def test_mac_only_script_archived_and_cross_platform_launchers_exist(self):
        self.assertFalse((ROOT / "deploy" / "setup-mac.sh").exists())
        self.assertTrue((ROOT / "archive" / "prototypes" / "setup-mac.sh").is_file())
        self.assertTrue((ROOT / "ownline.py").is_file())
        self.assertTrue((ROOT / "启动安装.bat").is_file())
        self.assertTrue((ROOT / "web" / "local-vault.html").is_file())

    def test_no_mac_lock_in_or_plaintext_secret_prompts_remain(self):
        self.assertNotIn("Mac", local_setup_progress.STAGES["delivery_verify"])
        local_setup_src = (ROOT / "web" / "src" / "html" / "local-setup.html").read_text(encoding="utf-8")
        for forbidden in ("Mac 本地安装", "这台 Mac", "从 Mac "):
            self.assertNotIn(forbidden, local_setup_src)

        for doc_rel in (
            "prompt/ssh_setup.md",
            "web/src/html/04-modals.html",
            "web/index.html",
            "README.md",
        ):
            content = (ROOT / doc_rel).read_text(encoding="utf-8")
            self.assertNotIn("[IP:端口:密码]", content, f"plaintext prompt left in {doc_rel}")
            self.assertNotIn("填入新服务器 IP、密码、密钥", content, f"plaintext prompt left in {doc_rel}")

        readme_prompts = (ROOT / "prompt" / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("../docs/设计/", readme_prompts)
        self.assertNotIn("../docs/核心文档/", readme_prompts)


if __name__ == "__main__":
    unittest.main()
