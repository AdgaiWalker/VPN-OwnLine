"""Isolated target bootstrap contracts with real signed configurations and node files."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from bootstrap_target import bootstrap
from nodekit import provenance, templates
from nodekit.node_manager import FileNodeStore, NodeManager


class BootstrapTargetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        (self.repo / "deploy").mkdir(parents=True)
        (self.repo / "deploy" / "install.sh").write_text("#!/bin/sh\nexit 0\n")
        self.data = self.root / "data"
        self.cfg = self.root / "proxy" / "config.json"
        self.cfg.parent.mkdir()
        self.manifest = self.root / "manifest.json"
        self.secret = bytes.fromhex("11" * 32)
        self.job = {
            "job_id": "a" * 32, "ip": "203.0.113.8", "name": "Target",
            "user": "root", "ssh_port": 2222, "node": {"pbk": "A" * 43},
            "actual_role": "exit", "control_secret": self.secret.hex(),
            "sub_token": "b" * 64, "panel_hash": "$2b$12$" + "A" * 53,
            "self_bootstrap": True,
        }
        self.config = templates.exit_config(
            9443, "actual-uuid", "actual.sni", "REALITY_PRIVATE_NOT_IN_RECORD", "12345678",
            hy2={"port": 9444, "password": "actual-hy2", "obfs_password": "actual-obfs", "sni": "quic.sni"},
        )
        self.sign(self.config)
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0))

    def sign(self, config, *, ip=None, secret=None):
        content = json.dumps(config).encode()
        self.cfg.write_bytes(content)
        self.manifest.write_text(json.dumps(provenance.sign_provenance(
            ip or self.job["ip"], provenance.compute_config_sha256(content), secret or self.secret,
        )))

    def call(self, job=None):
        return bootstrap(job or self.job, self.repo, self.data, self.cfg, self.runner,
                         provenance_path=self.manifest)

    def test_actual_channels_and_ownership_registered_before_panel_install(self):
        before = self.cfg.read_bytes()
        result = self.call()
        self.assertEqual(result, {"delivery": {"domain": "203-0-113-8.sslip.io", "sub_token": "b" * 64}})
        manager = NodeManager(store=FileNodeStore(self.data / "nodes.json"))
        main = manager.get_node("Target")
        quic = manager.get_node("Target-HY2")
        self.assertEqual((main["port"], main["uuid"], main["sid"]), (9443, "actual-uuid", "12345678"))
        self.assertEqual((quic["port"], quic["password"], quic["obfs_password"]), (9444, "actual-hy2", "actual-obfs"))
        self.assertFalse(main["warp_enabled"])
        self.assertEqual(main["group_id"], quic["group_id"])
        for node in (main, quic):
            self.assertTrue(node["local"])
            self.assertEqual(node["provenance_id"], self.job["ip"])
            self.assertNotIn("control_secret", node)
            self.assertNotIn("private_key", node)
        self.assertEqual(self.cfg.read_bytes(), before)
        self.assertEqual(provenance.load_master_secret(self.data), self.secret)
        self.assertEqual(os.stat(self.data / "master_secret").st_mode & 0o777, 0o600)
        self.assertNotIn("REALITY_PRIVATE_NOT_IN_RECORD", (self.data / "nodes.json").read_text())
        args, kwargs = self.runner.call_args
        self.assertEqual(args[0], ["bash", str(self.repo / "deploy" / "install.sh"), "--setup-stdin"])
        self.assertEqual(kwargs["input"].splitlines(), [self.job["job_id"], self.job["sub_token"], self.job["panel_hash"], "203-0-113-8.sslip.io", self.job["ip"]])
        self.assertNotIn(self.secret.hex(), kwargs["input"])

    def test_missing_forged_wrong_target_or_changed_config_never_installs(self):
        for fault in ("missing", "forged", "target", "config"):
            with self.subTest(fault=fault):
                self.sign(self.config)
                if fault == "missing":
                    self.manifest.unlink()
                elif fault == "forged":
                    self.sign(self.config, secret=b"wrong-key")
                elif fault == "target":
                    self.sign(self.config, ip="203.0.113.9")
                else:
                    self.cfg.write_text(self.cfg.read_text() + " ")
                with self.assertRaisesRegex(ValueError, "归属未验证"):
                    self.call()
                self.runner.assert_not_called()
                self.assertFalse(self.data.exists())

    def test_existing_signing_secret_mismatch_is_never_replaced(self):
        self.data.mkdir()
        key_path = self.data / "master_secret"
        key_path.write_text("22" * 32 + "\n")
        key_path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "签名密钥"):
            self.call()
        self.assertEqual(key_path.read_text(), "22" * 32 + "\n")
        self.assertFalse((self.data / "nodes.json").exists())
        self.runner.assert_not_called()

    def test_matching_seed_metadata_and_config_are_preserved_on_retry(self):
        self.call()
        manager = NodeManager(store=FileNodeStore(self.data / "nodes.json"))
        manager.update_nodes(lambda ns: [dict(n, custom_metadata="keep") for n in ns])
        nodes_before = (self.data / "nodes.json").read_bytes()
        cfg_before = self.cfg.read_bytes()
        self.call()
        self.assertEqual((self.data / "nodes.json").read_bytes(), nodes_before)
        self.assertEqual(self.cfg.read_bytes(), cfg_before)

    def test_existing_unrelated_node_or_settings_refuses_install(self):
        self.data.mkdir()
        manager = NodeManager(store=FileNodeStore(self.data / "nodes.json"))
        manager.add_node({"name": "Existing", "host": "203.0.113.50", "port": 443})
        before = (self.data / "nodes.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "底账"):
            self.call()
        self.assertEqual((self.data / "nodes.json").read_bytes(), before)
        self.runner.assert_not_called()

    def test_existing_subscription_mismatch_refuses_install(self):
        self.data.mkdir()
        (self.data / "settings.json").write_text(json.dumps({"sub_token": "old", "domain": "other.example"}))
        with self.assertRaisesRegex(ValueError, "后台设置"):
            self.call()
        self.assertFalse((self.data / "master_secret").exists())
        self.runner.assert_not_called()

    def test_failed_child_returns_no_delivery(self):
        self.runner.return_value = subprocess.CompletedProcess([], 1)
        with self.assertRaisesRegex(ValueError, "安装未完成"):
            self.call()

    def test_ssh_credentials_and_protocol_injection_are_rejected(self):
        jobs = []
        for key in ("password", "private_key", "passphrase", "ssh_password", "ssh_private_key"):
            job = deepcopy(self.job)
            job[key] = "test-login-secret"
            jobs.append(job)
            nested = deepcopy(self.job)
            nested["node"][key] = "test-login-secret"
            jobs.append(nested)
        job = deepcopy(self.job)
        job["panel_hash"] += "\ninjected"
        jobs.append(job)
        for job in jobs:
            with self.subTest(fields=sorted(job)):
                with self.assertRaises(ValueError):
                    self.call(job)
                self.runner.assert_not_called()
                self.assertFalse(self.data.exists())

    def test_relay_metadata_is_read_from_signed_live_config(self):
        landing = {"host": "203.0.113.99", "port": 443, "uuid": "landing-id", "sni": "landing.sni", "pbk": "B" * 43, "sid": "abcd"}
        self.config = templates.relay_config(9443, "relay-id", "relay.sni", "private", "abcd", landing)
        self.sign(self.config)
        job = dict(self.job, actual_role="relay", landing=landing)
        self.call(job)
        main = NodeManager(store=FileNodeStore(self.data / "nodes.json")).get_node("Target")
        self.assertEqual(main["role"], "relay")
        self.assertEqual(main["landing"], landing)
        self.assertIsNone(NodeManager(store=FileNodeStore(self.data / "nodes.json")).get_node("Target-HY2"))


if __name__ == "__main__":
    unittest.main()
