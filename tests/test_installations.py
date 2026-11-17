"""Installation capabilities, anonymous credentials and truthful delivery, offline."""
import base64
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
import admin
from nodekit import installations, ssh_memory
from nodekit.store import AtomicJsonStore


def increment(path, barrier):
    barrier.wait()
    for _ in range(15):
        AtomicJsonStore.update(path, lambda value: value + 1, default=0)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        key = b"fixture-host-key"
        self.identity = {"address": "8.8.8.8", "ready_for_install": True, "machine_id": "b" * 32,
                         "host_key_type": "ssh-ed25519", "host_key": base64.b64encode(key).decode(),
                         "fingerprint": "SHA256:" + base64.b64encode(hashlib.sha256(key).digest()).decode().rstrip("=")}
        self.login = {"host": "fixture.example", "username": "root", "ssh_port": 2222,
                      "private_key": "fixture-private-key", "passphrase": "fixture-phrase"}

    def checked(self):
        targets = installations.CheckedTargets()
        return targets.take(targets.remember(self.login, self.identity))

    def test_capability_single_use_expiry_and_bounded_retention(self):
        now = [0]
        targets = installations.CheckedTargets(ttl=10, limit=1, clock=lambda: now[0])
        token = targets.remember(self.login, self.identity)
        with self.assertRaises(installations.InstallError):
            targets.remember(self.login, self.identity)
        record = targets.take(token)
        self.assertEqual(record["login"]["passphrase"], "fixture-phrase")
        self.assertEqual(record["login"]["host"], "8.8.8.8")
        with self.assertRaises(installations.InstallError):
            targets.take(token)
        token = targets.remember(self.login, self.identity)
        now[0] = 11
        with self.assertRaises(installations.InstallError):
            targets.take(token)

    def test_identity_and_readiness_fail_closed(self):
        for change in ({"ready_for_install": False}, {"machine_id": "invalid"},
                       {"address": "127.0.0.1"}, {"fingerprint": "SHA256:" + "A" * 43}):
            with self.subTest(change=change), self.assertRaises(installations.InstallError):
                installations.CheckedTargets().remember(self.login, dict(self.identity, **change))

    def test_checked_login_retains_canonical_account_and_port_defaults(self):
        targets = installations.CheckedTargets()
        token = targets.remember({"host": "fixture.example", "password": "fixture"}, self.identity)
        login = targets.take(token)["login"]
        self.assertEqual((login["username"], login["ssh_port"]), ("root", 22))

    def test_memory_job_adapter_never_writes_a_secret(self):
        with tempfile.TemporaryDirectory() as td, patch.object(admin, "DATA", td):
            spec = admin._write_job("fixture", {"auth_type": "key"}, "fixture-secret")
            self.assertEqual(spec["private_key"], "fixture-secret")
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_check_api_issues_redacted_ticket_and_legacy_link_installs_use_same_identity(self):
        for prefix in ("", "/api"):
            targets = installations.CheckedTargets()
            output = []
            handler = SimpleNamespace(path=prefix + "/node/check", headers=Mock(),
                                      _json=lambda code, body: output.append((code, body)))
            handler.headers.get_content_type.return_value = "application/json"
            with patch.object(admin, "CHECKED_TARGETS", targets), \
                 patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-install-test-marker")), \
                 patch.object(admin.http_utils, "validate_origin", return_value=True), \
                 patch.object(admin.http_utils, "parse_json_body", return_value=(200, self.login)), \
                 patch.object(admin.node_check_bridge, "check", return_value={"ok": True, "result": self.identity}):
                admin.H.do_POST(handler)
            self.assertEqual(output[0][0], 200)
            self.assertNotIn("fixture-phrase", json.dumps(output))
            token = output[0][1]["check_ticket"]
            handler.path = prefix + "/addnode"
            payload = {"check_ticket": token, "name": "Relay", "role": "relay", "self_bootstrap": False,
                       "landing": {"link": "vless://12345678-1234-1234-1234-123456789abc@1.1.1.1:443?security=reality&pbk=" + "A" * 43 + "&sid=12345678&sni=www.apple.com#Exit"}}
            with patch.object(admin, "CHECKED_TARGETS", targets), \
                 patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-install-test-marker")), \
                 patch.object(admin.http_utils, "validate_origin", return_value=True), \
                 patch.object(admin.http_utils, "parse_json_body", return_value=(200, payload)), \
                 patch.object(admin, "load_nodes", return_value=[]), \
                 patch.object(admin, "_gen_node", return_value={}), \
                 patch.object(admin.threading, "Thread") as thread, patch.dict(admin.JOBS):
                admin.H.do_POST(handler)
                self.assertEqual(output[-1][0], 200)
                spec = thread.call_args.kwargs["args"][1]
                self.assertEqual(spec["landing"]["host"], "1.1.1.1")
                self.assertEqual(spec["checked_target"]["login"]["passphrase"], "fixture-phrase")
                thread.return_value.start.assert_called_once()
            with self.assertRaises(installations.InstallError):
                targets.take(token)

    def test_standalone_reserved_port_is_rejected_before_start(self):
        for port in (80, 8443):
            targets = installations.CheckedTargets()
            token = targets.remember(self.login, self.identity)
            captured = []
            handler = SimpleNamespace(path="/api/addnode", headers={}, _json=lambda code, body: captured.append((code, body)))
            with patch.object(admin, "CHECKED_TARGETS", targets), \
                 patch.object(admin, "INITIAL_PASSWORD_MARKER", Path("/nonexistent-install-test-marker")), \
                 patch.object(admin.http_utils, "parse_json_body", return_value=(200, {"check_ticket":token,"port":port})), \
                 patch.object(admin, "load_nodes", return_value=[]), patch.object(admin, "_load_json", return_value={}), \
                 patch.object(admin, "_gen_node") as generate, patch.object(admin.threading, "Thread") as thread:
                admin.H.do_POST(handler)
                self.assertEqual(captured[0][0], 400)
                generate.assert_not_called()
                thread.assert_not_called()

    def test_changed_target_never_launches_installer(self):
        spec = {"checked_target": self.checked()}
        jid = "fixture-changed"
        with patch.dict(admin.JOBS, {jid: {"state": "queued", "log": []}}), \
             patch.object(admin.node_check_bridge, "check", return_value={"ok": True, "result": dict(self.identity, machine_id="c" * 32)}), \
             patch.object(admin.subprocess, "Popen") as process:
            admin.run_job(jid, spec)
            process.assert_not_called()
            self.assertEqual(admin.JOBS[jid]["state"], "error")
            self.assertNotIn("delivery", admin.JOBS[jid])
        self.assertEqual(spec, {})

    def run_worker(self, health, candidate, bootstrap=True, dry=False):
        node = {"name": "fixture-node", "host": "8.8.8.8", "port": 443, "type": "vless"}
        events = [node] + ([{"delivery": candidate}] if candidate else [])
        class Input(io.StringIO):
            def close(self):
                self.saved = self.getvalue()
                super().close()
        process = Mock(stdin=Input(), stdout=io.StringIO("\n".join(json.dumps(item) for item in events)))
        process.wait.return_value = 0
        process.poll.return_value = 0
        spec = {"checked_target": self.checked(), "control_secret": "a" * 64,
                "node": {"initial_password": "fixture-panel-pass"}, "self_bootstrap": bootstrap, "dry_run": dry}
        jid = "fixture-job"
        with patch.dict(admin.JOBS, {jid: {"state": "queued", "log": []}}), \
             patch.object(admin.node_check_bridge, "check", return_value={"ok": True, "result": self.identity}), \
             patch.object(admin.subprocess, "Popen", return_value=process), \
             patch.object(admin.install_mod, "pin_known_host"), \
             patch.object(admin.verify_mod, "run", return_value={"health": health}), \
             patch.object(admin, "open_firewall", return_value=("opened", "fixture")) as firewall, \
             patch.object(admin.node_manager, "add_node"), \
             patch.object(admin.install_mod, "verify_delivery", return_value={"kind": "standalone", "direct_sub_url": "https://fixture/s/" + "b" * 64}) as verify:
            admin.run_job(jid, spec)
            payload = json.loads(process.stdin.saved)
            self.assertEqual(payload["passphrase"], "fixture-phrase")
            self.assertEqual(payload["machine_id"], "b" * 32)
            self.assertEqual(payload["ip"], "8.8.8.8")
            expected = set() if dry else {(443, "TCP"), (443, "UDP")} | ({(80, "TCP"), (8443, "TCP")} if bootstrap else set())
            self.assertEqual({(call.args[1], call.kwargs["proto"]) for call in firewall.call_args_list}, expected)
            return dict(admin.JOBS[jid]), verify.call_count

    def test_failed_proxy_or_missing_backend_never_delivers_assets(self):
        failed, calls = self.run_worker("proxy", {"domain": "fixture"})
        self.assertEqual(failed["state"], "error")
        self.assertNotIn("delivery", failed)
        self.assertEqual(calls, 0)
        missing, calls = self.run_worker("ok", None)
        self.assertEqual(missing["state"], "error")
        self.assertNotIn("delivery", missing)
        self.assertEqual(calls, 0)

    def test_dry_run_never_opens_cloud_firewall_or_delivers_assets(self):
        result, calls = self.run_worker("ok", None, dry=True)
        self.assertEqual((result["state"], result["warn"], calls), ("done", "dry_run", 0))
        self.assertNotIn("delivery", result)

    def test_verified_backend_and_managed_node_have_distinct_delivery(self):
        ready, calls = self.run_worker("ok", {"domain": "fixture"})
        self.assertEqual((ready["state"], ready["delivery"]["kind"], calls), ("done", "standalone", 1))
        managed, calls = self.run_worker("ok", None, bootstrap=False)
        self.assertEqual((managed["state"], managed["delivery"]["kind"], calls), ("done", "managed_node", 0))
        self.assertNotIn("dashboard_url", managed["delivery"])

    def test_backend_probes_pin_address_and_require_all_assets(self):
        made = []
        statuses = iter([401, 200, 200])
        def factory(domain, address):
            made.append((domain, address))
            response = Mock(status=next(statuses))
            response.read.return_value = b"fixture-subscription"
            return Mock(getresponse=Mock(return_value=response))
        candidate = {"domain": "8-8-8-8.sslip.io", "sub_token": "a" * 64}
        result = installations.verify_delivery(candidate, "8.8.8.8", "fixture-password", factory)
        self.assertEqual(result["kind"], "standalone")
        self.assertEqual(made, [("8-8-8-8.sslip.io", "8.8.8.8")] * 3)
        with self.assertRaises(installations.InstallError):
            installations.verify_delivery(dict(candidate, domain="evil.example"), "8.8.8.8", "fixture-password", factory, attempts=1)
        with self.assertRaises(installations.InstallError):
            installations.verify_delivery(candidate, "8.8.8.8", "fixture-password", lambda *_: Mock(getresponse=Mock(return_value=Mock(status=403))), attempts=1)

    def test_backend_certificate_propagation_retries_without_installing_again(self):
        count = [0]
        def factory(*_):
            count[0] += 1
            if count[0] == 1:
                raise OSError("fixture startup")
            response = Mock(status=401 if count[0] == 2 else 200)
            response.read.return_value = b"subscription"
            return Mock(getresponse=Mock(return_value=response))
        sleep = Mock()
        result = installations.verify_delivery({"domain": "8-8-8-8.sslip.io", "sub_token": "a" * 64},
                                               "8.8.8.8", "fixture", factory, sleep=sleep)
        self.assertEqual(result["kind"], "standalone")
        sleep.assert_called_once_with(2)

    def test_ssh_anonymous_adapter_preserves_phrase_without_argv_or_env(self):
        files = []
        def memory_file(_name):
            stream = tempfile.TemporaryFile()
            files.append(stream)
            return os.dup(stream.fileno())
        job = dict(self.login, ip="8.8.8.8", user="root", host_key_type=self.identity["host_key_type"], host_key=self.identity["host_key"])
        def runner(command, **kwargs):
            self.assertNotIn("fixture-private-key", " ".join(command))
            self.assertNotIn("fixture-phrase", " ".join(command))
            self.assertNotIn("env", kwargs)
            password_fd = int(command[command.index("-d") + 1])
            self.assertEqual(os.read(password_fd, 100), b"fixture-phrase\n")
            self.assertIn(password_fd, kwargs["pass_fds"])
            self.assertTrue(any("UserKnownHostsFile=/proc/" in item for item in command))
            return 0
        try:
            self.assertEqual(ssh_memory.run(job, ["uname -m"], runner, memory_file), 0)
        finally:
            for stream in files:
                stream.close()

    def test_bundle_contains_full_deploy_without_local_data(self):
        stream = io.BytesIO()
        installations.emit_bundle(ROOT / "server", stream)
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:gz") as archive:
            names = set(archive.getnames())
        self.assertTrue({"deploy/upgrade.sh", "deploy/runtime_manifest.py", "server/bootstrap_target.py", "requirements.lock"}.issubset(names))
        self.assertFalse(any(".ops-private" in name or ".jobs" in name or "nodes.json" in name for name in names))

    def test_checked_host_is_pinned_for_followup_control_and_conflicts_rejected(self):
        checked = self.checked()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "known_hosts"
            installations.pin_known_host(checked, path)
            content = path.read_text()
            self.assertIn("[8.8.8.8]:2222 ssh-ed25519", content)
            self.assertNotIn("fixture-phrase", content)
            same = Mock(return_value=SimpleNamespace(returncode=0, stdout=content))
            installations.pin_known_host(checked, path, same)
            self.assertEqual(path.read_text(), content)
            conflict = Mock(return_value=SimpleNamespace(returncode=0, stdout="[8.8.8.8]:2222 ssh-ed25519 other-key\n"))
            with self.assertRaises(installations.InstallError):
                installations.pin_known_host(checked, path, conflict)
            self.assertEqual(path.read_text(), content)

    def test_cross_process_updates_are_serialized(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "count.json")
            context = multiprocessing.get_context("spawn")
            barrier = context.Barrier(3)
            workers = [context.Process(target=increment, args=(path, barrier)) for _ in range(3)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(20)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(AtomicJsonStore.load(path), 45)


if __name__ == "__main__":
    unittest.main()
