"""Offline contract tests for real task/HTTP behavior; no SSH target is contacted."""

import base64
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash
from server.installer import provision, tencent_discovery
from server.installer.service import Config, Worker, create_app
from server.installer.state import Problem, Store
from server.installer.transport import inspect, normalize

ROOT = Path(__file__).resolve().parents[2]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.req = {
            "target_key": "192.0.2.1:2222",
            "host": "192.0.2.1",
            "credential_ref": "opaque",
        }

    def test_duplicate_submission_returns_original_and_changed_body_is_rejected(self):
        jid, _ = self.store.create("install", self.req, "a" * 16)
        self.assertEqual((jid, False), self.store.create("install", self.req, "a" * 16))
        with self.assertRaises(Problem) as e:
            self.store.create("install", {**self.req, "host": "different"}, "a" * 16)
        self.assertEqual("IDEMPOTENCY_CONFLICT", e.exception.code)

    def test_target_conflict_survives_worker_restart_and_different_key(self):
        jid, _ = self.store.create("install", self.req, "a" * 16)
        self.store.next()
        other = Store(self.temp.name)
        other.recover()
        self.assertEqual("awaiting_credentials", other.get(jid)["state"])
        with self.assertRaises(Problem) as e:
            other.create("install", self.req, "b" * 16)
        self.assertEqual(jid, e.exception.detail["job_id"])

    def test_database_refuses_credentials(self):
        for field in (
            "password",
            "private_key",
            "passphrase",
            "sub_token",
            "admin_password",
        ):
            with self.assertRaises(ValueError):
                self.store.create("check", {**self.req, field: "secret"})
        self.assertEqual(0o600, self.store.path.stat().st_mode & 0o777)

    def test_stage_events_are_bounded_and_recoverable(self):
        jid, _ = self.store.create("check", self.req)
        for i in range(205):
            self.store.update(jid, "running", "check", "Checking target")
        with self.store.db() as db:
            count = db.execute("select count(*) from events").fetchone()[0]
        self.assertEqual(200, count)
        self.assertEqual(30, len(self.store.get(jid)["events"]))


class APItests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.auth_hash = generate_password_hash("test password only")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        config = {
            "data_dir": self.temp.name + "/data",
            "source_dir": str(ROOT),
            "origin": "http://127.0.0.1:4180",
            "development": True,
            "auth_hash": self.auth_hash,
            "csrf_key": "a" * 64,
        }
        path = Path(self.temp.name) / "config.json"
        path.write_text(json.dumps(config))
        self.config = Config(path)
        self.client = create_app(self.config).test_client()
        self.auth = {
            "Authorization": "Basic "
            + base64.b64encode(b"admin:test password only").decode()
        }
        token = self.client.get("/api/setup", headers=self.auth).json["csrf_token"]
        self.headers = {**self.auth, "Origin": config["origin"], "X-CSRF-Token": token}

    def test_auth_and_source_validation(self):
        self.assertEqual(401, self.client.get("/api/setup").status_code)
        for changes in ({"Origin": "https://evil.example"}, {"X-CSRF-Token": "bad"}):
            r = self.client.post(
                "/api/checks", json={}, headers={**self.headers, **changes}
            )
            self.assertEqual(403, r.status_code)

    def test_invalid_json_shape_is_a_clear_error(self):
        for body in ([], None, "text", 42):
            r = self.client.post(
                "/api/checks",
                data=json.dumps(body),
                content_type="application/json",
                headers=self.headers,
            )
            self.assertEqual(400, r.status_code)
            self.assertEqual("INVALID_BODY", r.json["code"])

    def test_secret_input_is_only_sent_to_memory_rpc(self):
        with (
            patch(
                "server.installer.service.normalize",
                return_value={"target_key": "192.0.2.1:22"},
            ),
            patch(
                "server.installer.service.provision.bundle",
                return_value=("fixed", "archive"),
            ),
            patch(
                "server.installer.service.rpc", return_value={"job_id": "example"}
            ) as call,
        ):
            response = self.client.post(
                "/api/checks", json={"password": "temporary-only"}, headers=self.headers
            )
        self.assertEqual(202, response.status_code)
        self.assertEqual("temporary-only", call.call_args[0][2]["secret"]["password"])
        self.assertNotIn(b"temporary-only", self.config.store.path.read_bytes())

    def test_tencent_discovery_requires_auth_and_csrf_and_does_not_persist_keys(self):
        body = {"secret_id": "id-fixture", "secret_key": "key-fixture"}
        self.assertEqual(401, self.client.post("/api/tencent/instances", json=body).status_code)
        self.assertEqual(403, self.client.post("/api/tencent/instances", json=body, headers=self.auth).status_code)
        with patch("server.installer.service.tencent_discovery.discover", return_value={"instances": [], "incomplete_regions": []}) as lookup:
            result = self.client.post("/api/tencent/instances", json=body, headers=self.headers)
        self.assertEqual(200, result.status_code)
        lookup.assert_called_once_with("id-fixture", "key-fixture")
        self.assertNotIn("key-fixture", result.text)
        self.assertNotIn(b"key-fixture", self.config.store.path.read_bytes())

    def checked(self, expires=None):
        req = {
            "target_key": "192.0.2.1:2222",
            "host": "192.0.2.1",
            "address": "192.0.2.1",
            "ssh_port": 2222,
            "username": "root",
            "fingerprint": "pin",
            "release_id": "release",
            "archive": "archive",
            "credential_ref": "opaque",
        }
        jid, _ = self.config.store.create("check", req)
        self.config.store.update(
            jid,
            "succeeded",
            "checked",
            "Checked",
            {
                "fingerprint": "pin",
                "machine_id": "machine",
                "expires_at": expires or time.time() + 300,
            },
        )
        return jid, req

    def test_install_requires_confirmation_and_prior_check(self):
        jid, _ = self.checked()
        r = self.client.post(
            "/api/jobs",
            json={"check_job_id": jid},
            headers={**self.headers, "Idempotency-Key": "a" * 16},
        )
        self.assertEqual("CONFIRMATION_REQUIRED", r.json["code"])

    def test_expired_check_does_not_start_installation(self):
        jid, req = self.checked(time.time() - 1)
        with patch("server.installer.service.normalize", return_value=req):
            r = self.client.post(
                "/api/jobs",
                json={"check_job_id": jid, "confirm_install": True},
                headers={**self.headers, "Idempotency-Key": "a" * 16},
            )
        self.assertEqual("CHECK_EXPIRED", r.json["code"])
        self.assertIsNone(self.config.store.next())

    def test_public_job_never_exposes_secret_reference(self):
        jid, _ = self.checked()
        r = self.client.get("/api/jobs/" + jid, headers=self.auth)
        self.assertEqual(
            {"host": "192.0.2.1", "ssh_port": 2222, "username": "root"},
            r.json["target"],
        )
        self.assertNotIn("request", r.json)
        self.assertNotIn("credential_ref", r.text)
        self.assertEqual("no-store", r.headers["Cache-Control"])

    def test_production_disallows_test_certificate_override(self):
        self.config.raw.update(
            origin="https://setup.example.com",
            development=False,
            tls_ca_file="/test.crt",
        )
        p = Path(self.temp.name) / "bad.json"
        p.write_text(json.dumps(self.config.raw))
        with self.assertRaises(ValueError):
            Config(p)

    def test_credentials_expire_and_worker_restart_has_no_secret(self):
        worker = Worker(self.config)
        ref = worker.keep({"password": "in-memory"})
        self.assertEqual("in-memory", worker.take(ref)["password"])
        with self.assertRaises(Problem):
            Worker(self.config).take(ref)
        worker.secrets[ref] = (0, {"password": "expired"})
        with self.assertRaises(Problem):
            worker.take(ref)


class BoundaryTests(unittest.TestCase):
    def test_tencent_pagination_and_partial_region_failure(self):
        def call(action, payload, sid, key, region):
            if action == "DescribeRegions":
                return {"Response": {"RegionSet": [{"Region": "ap-singapore", "RegionName": "新加坡"}, {"Region": "ap-tokyo", "RegionName": "东京"}]}}
            if region == "ap-tokyo":
                return {"Response": {"Error": {"Code": "UnauthorizedOperation", "Message": "secret should never be echoed"}}}
            offset = payload["Offset"]
            return {"Response": {"InstanceSet": [{"InstanceId": f"id-{i}", "InstanceName": "server", "PublicAddresses": ["8.8.8.8"], "InstanceState": "RUNNING"} for i in range(offset, 50 if offset == 0 else 51)]}}

        with patch("server.installer.tencent_discovery.tc3.call", side_effect=call):
            result = tencent_discovery.discover("id-fixture", "key-fixture")
        self.assertEqual(51, len(result["instances"]))
        self.assertEqual(["东京"], result["incomplete_regions"])
        self.assertNotIn("key-fixture", json.dumps(result))

    def test_tencent_auth_and_network_errors_are_not_empty_results(self):
        with patch("server.installer.tencent_discovery.tc3.call", return_value={"Response": {"Error": {"Code": "AuthFailure.SecretIdNotFound", "Message": "private"}}}):
            with self.assertRaises(Problem) as caught:
                tencent_discovery.discover("id", "secret")
        self.assertEqual("TENCENT_AUTH_FAILED", caught.exception.code)
        self.assertNotIn("private", str(caught.exception))
        with patch("server.installer.tencent_discovery.tc3.call", side_effect=OSError("private")):
            with self.assertRaises(Problem) as caught:
                tencent_discovery.discover("id", "secret")
        self.assertEqual("TENCENT_UNAVAILABLE", caught.exception.code)
        self.assertNotIn("private", str(caught.exception))

    def test_windows_detection_never_enables_linux_install(self):
        class Fake:
            fingerprint = "p"

            def python(self, _):
                raise Problem("REMOTE_CHECK_FAILED", "not Linux")

            def run(self, command):
                self.asserted_command = command
                return 0, json.dumps({
                    "os": "windows", "version": "10.0", "architecture": "AMD64",
                    "singbox_running": True, "singbox_listen_ports": [8443],
                }).encode(), b""

        ssh = Fake()
        result = inspect(ssh)
        self.assertFalse(result["compatible"])
        self.assertTrue(result["singbox_running"])
        self.assertEqual([8443], result["singbox_listen_ports"])
        self.assertIn("-EncodedCommand", ssh.asserted_command)

    def test_windows_probe_does_not_mask_ssh_errors(self):
        class Fake:
            def python(self, _):
                raise Problem("SSH_TIMEOUT", "timeout")

        with self.assertRaises(Problem) as caught:
            inspect(Fake())
        self.assertEqual("SSH_TIMEOUT", caught.exception.code)

    def test_loopback_requires_explicit_operator_allowlist(self):
        with self.assertRaises(Problem):
            normalize({"host": "127.0.0.1"})
        self.assertEqual(
            2222,
            normalize({"host": "127.0.0.1", "ssh_port": 2222}, ["127.0.0.1"])[
                "ssh_port"
            ],
        )

    def test_old_os_and_non_root_are_rejected(self):
        class Fake:
            fingerprint = "p"

            def python(self, _):
                return dict(self.result)

        ssh = Fake()
        base = {
            "root": True,
            "systemd": True,
            "architecture": "aarch64",
            "os": "ubuntu",
            "version": "22.04",
            "disk_mb": 1000,
        }
        for updates, expected in (
            ({}, True),
            ({"version": "20.04"}, False),
            ({"root": False}, False),
            ({"os": "debian", "version": "12"}, True),
            ({"architecture": "armv7l"}, False),
        ):
            ssh.result = {**base, **updates}
            self.assertEqual(expected, inspect(ssh)["compatible"])

    def test_bundle_immutable_and_excludes_credentials(self):
        import tarfile
        import hashlib

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            data = Path(tmp) / "data"
            source.mkdir()
            data.mkdir()
            (source / "server").mkdir()
            (source / "server/a.py").write_text("pass")
            (source / "server/.jobs").mkdir()
            (source / "server/.jobs/job.secret").write_text("never-transfer")
            (source / "private").mkdir()
            (source / "private/key").write_text("never-transfer")
            first = provision.bundle(source, data)
            second = provision.bundle(source, data)
            self.assertEqual(first, second)
            self.assertEqual(
                first[0], hashlib.sha256(Path(first[1]).read_bytes()).hexdigest()
            )
            with tarfile.open(first[1]) as t:
                self.assertNotIn("server/.jobs/job.secret", t.getnames())


class WorkerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = type("Config", (), {"store": Store(self.temp.name)})()
        self.worker = Worker(self.config)
        self.req = {
            "target_key": "192.0.2.1:22",
            "host": "192.0.2.1",
            "credential_ref": self.worker.keep({"password": "memory-only"}),
            "machine_id": "machine",
            "fingerprint": "pin",
        }

    def test_existing_configuration_is_never_deployed_over(self):
        jid, _ = self.config.store.create("check", self.req)
        with (
            patch("server.installer.service.SSH"),
            patch(
                "server.installer.service.inspect",
                return_value={"compatible": True, "existing": True},
            ),
            patch("server.installer.provision.deploy") as deploy,
        ):
            self.worker.run_one(jid)
        self.assertEqual(
            "EXISTING_INSTALLATION", self.config.store.get(jid)["error_code"]
        )
        deploy.assert_not_called()

    def test_protected_target_cannot_be_delivered_or_restarted(self):
        jid, _ = self.config.store.create("install", self.req)
        with (
            patch("server.installer.service.SSH") as ssh,
            patch(
                "server.installer.service.inspect",
                return_value={"machine_id": "machine"},
            ),
            patch(
                "server.installer.provision.status",
                return_value={"state": "installed", "quota_paused": True},
            ),
            patch("server.installer.provision.verify") as verify,
            patch("server.installer.provision.deploy") as deploy,
        ):
            ssh.return_value.fingerprint = "pin"
            self.worker.run_one(jid)
        self.assertEqual("QUOTA_PROTECTED", self.config.store.get(jid)["error_code"])
        verify.assert_not_called()
        deploy.assert_not_called()

    def test_existing_binaries_do_not_force_an_unnecessary_download(self):
        self.config.dev = False
        self.config.raw = {}
        self.req["archive"] = "existing-release"
        jid, _ = self.config.store.create("install", self.req)
        snapshot = {
            "machine_id": "machine",
            "architecture": "aarch64",
            "existing": False,
            "compatible": True,
            "singbox_installed": True,
            "caddy_installed": True,
        }
        with (
            patch("server.installer.service.SSH") as ssh,
            patch("server.installer.service.inspect", return_value=snapshot),
            patch(
                "server.installer.provision.status",
                side_effect=[{"state": "not_started"}, {"state": "failed"}],
            ),
            patch("server.installer.provision.deploy") as deploy,
            patch("server.installer.downloads.prepare") as prepare,
        ):
            ssh.return_value.fingerprint = "pin"
            self.worker.run_one(jid)
        deploy.assert_called_once()
        prepare.assert_not_called()
