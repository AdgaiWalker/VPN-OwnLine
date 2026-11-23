"""Offline ownership regressions through config, rollback, quota and repair Interfaces."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from nodekit import provenance, quota_guard, remote_config, remote_config_tests, repair, templates


@contextmanager
def owned_target():
    initial = templates.exit_config(port=443, uuid="11111111-1111-4111-8111-111111111111",
                                   sni="www.apple.com", private_key="OWNED_PRIVATE", sid="abcd1234")
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg, binary, env, runner, calls = remote_config_tests._make_sandbox(tmp, initial)
        node = {"name": "before rename", "host": "203.0.113.44", "role": "exit"}
        remote_config.run_target(node, "true", runner=runner)
        yield node, root, Path(cfg), binary, env, runner, calls, initial


def command_script(cmd):
    return base64.b64decode(cmd[-1].split()[1]).decode() if cmd[0] == "ssh" else cmd[-1]


class ServiceOwnershipTests(unittest.TestCase):
    secret = remote_config_tests.SECRET

    def test_every_mutation_rejects_missing_forged_wrong_target_and_changed_config(self):
        for fault in ("missing", "forged", "target", "config"):
            with self.subTest(fault=fault), owned_target() as target:
                node, root, cfg, binary, env, runner, calls, initial = target
                prov = cfg.parent / ".evergreen-provenance.json"
                manifest = json.loads(prov.read_text())
                if fault == "missing":
                    prov.unlink()
                elif fault == "forged":
                    manifest["signature"] = "0" * 64
                    prov.write_text(json.dumps(manifest))
                elif fault == "target":
                    prov.write_text(json.dumps(provenance.sign_provenance("203.0.113.45", manifest["config_sha256"], self.secret)))
                else:
                    cfg.write_text(cfg.read_text() + " ")
                before = cfg.read_bytes()
                firewall_calls = []
                self.assertFalse(remote_config.toggle_hy2(
                    node, enabled=True, runner=runner, cfg_path=str(cfg), bin_path=binary,
                    master_secret=self.secret, open_firewall_fn=lambda *args, **kwargs: firewall_calls.append(args))["ok"])
                self.assertEqual(firewall_calls, [])
                with patch("nodekit.warp_client.register_warp") as register:
                    self.assertFalse(remote_config.toggle_warp(
                        node, enabled=True, runner=runner, cfg_path=str(cfg), bin_path=binary,
                        master_secret=self.secret)["ok"])
                    register.assert_not_called()
                applied, _ = remote_config.apply_config(node, initial, runner=runner, cfg_path=str(cfg),
                                                        bin_path=binary, master_secret=self.secret)
                self.assertFalse(applied)
                self.assertFalse(remote_config.rollback_config(node, runner=runner, cfg_path=str(cfg), bin_path=binary, master_secret=self.secret))
                for control in (quota_guard.stop_node_proxy, quota_guard.start_node_proxy):
                    self.assertNotEqual(control(node, runner=runner, cfg_path=str(cfg), master_secret=self.secret).returncode, 0)
                def execute(n, command, **kwargs):
                    command = command.replace(provenance.config_path(n), str(cfg))
                    return remote_config.run_target(n, command, runner=runner, **kwargs)
                result = repair.repair_node(node, execute_remote_fn=execute, master_secret=self.secret)
                self.assertFalse(result["ok"])
                self.assertTrue(result["requires_manual"])
                self.assertEqual(cfg.read_bytes(), before)
                self.assertFalse((root / "systemctl.log").exists())
                self.assertFalse((root / "ownline").exists())
                self.assertFalse(Path(str(cfg) + ".ownline.bak").exists())

    def test_locked_recheck_rejects_config_or_manifest_changed_after_read(self):
        for path_kind in ("config", "manifest"):
            with self.subTest(path=path_kind), owned_target() as target:
                node, root, cfg, binary, env, runner, calls, initial = target
                changed = False
                def drift(cmd, **kwargs):
                    nonlocal changed
                    if "flock -x" in command_script(cmd) and not changed:
                        path = cfg if path_kind == "config" else cfg.parent / ".evergreen-provenance.json"
                        path.write_bytes(path.read_bytes() + b" ")
                        changed = True
                    return runner(cmd, **kwargs)
                self.assertFalse(remote_config.apply_config(node, initial, runner=drift, cfg_path=str(cfg),
                                                             bin_path=binary, master_secret=self.secret)[0])
                self.assertTrue(changed)
                self.assertFalse((root / "systemctl.log").exists())
                self.assertFalse(Path(str(cfg) + ".ownline.bak").exists())

    def test_windows_mutations_frozen_fail_closed_before_dispatch(self):
        cfg = templates.exit_config(443, "11111111-1111-4111-8111-111111111111",
                                    "www.apple.com", "OWNED_PRIVATE", "abcd1234")
        for node in (
            {"name": "Windows", "host": "203.0.113.91", "os": "windows", "role": "exit"},
            {"name": "WindowsAdmin", "host": "203.0.113.92", "ssh_user": "Administrator", "role": "exit"},
        ):
            with self.subTest(node=node["name"]):
                reads, mutations = [], []

                def execute(n, script, **kwargs):
                    reads.append(script)
                    return subprocess.CompletedProcess([], 0, "", "")

                def runner(cmd, input=None, **kwargs):
                    mutations.append((cmd, input))
                    return subprocess.CompletedProcess([], 0, "", "")

                self.assertFalse(remote_config.apply_config(node, cfg, runner=runner, master_secret=self.secret, allow_windows=True)[0])
                self.assertFalse(remote_config.rollback_config(node, runner=runner, master_secret=self.secret))
                self.assertFalse(remote_config.toggle_hy2(node, enabled=True, runner=runner, master_secret=self.secret)["ok"])
                self.assertFalse(remote_config.sync_isp(node, {"type": "socks", "server": "198.51.100.1", "server_port": 1080}, runner=runner, master_secret=self.secret)["ok"])
                self.assertFalse(remote_config.toggle_warp(node, enabled=True, runner=runner, master_secret=self.secret)["ok"])
                self.assertFalse(repair.repair_node(node, execute_remote_fn=execute, runner=runner, master_secret=self.secret)["ok"])
                self.assertEqual(reads, [])
                self.assertEqual(mutations, [])

    def test_rename_and_signed_pair_rollback_preserve_ownership(self):
        with owned_target() as target:
            node, root, cfg, binary, env, runner, calls, initial = target
            prov = cfg.parent / ".evergreen-provenance.json"
            old_cfg, old_prov = cfg.read_bytes(), prov.read_bytes()
            node["name"] = "after rename"
            changed = json.loads(json.dumps(initial))
            changed["inbounds"][0]["listen_port"] = 8443
            self.assertTrue(remote_config.apply_config(node, changed, runner=runner, cfg_path=str(cfg),
                                                       bin_path=binary, master_secret=self.secret)[0])
            execute = lambda n, script, **kw: remote_config.run_target(n, script, runner=runner, **kw)
            self.assertTrue(provenance.verify_target(node, execute, self.secret, cfg_path=str(cfg))[0])
            self.assertTrue(remote_config.rollback_config(node, runner=runner, cfg_path=str(cfg), bin_path=binary, master_secret=self.secret))
            self.assertEqual(cfg.read_bytes(), old_cfg)
            self.assertEqual(prov.read_bytes(), old_prov)
            self.assertTrue(provenance.verify_target(node, execute, self.secret, cfg_path=str(cfg))[0])

    def test_failed_probe_rolls_back_when_binary_and_config_have_separate_directories(self):
        with owned_target() as target:
            node, root, cfg, binary, env, runner, calls, initial = target
            moved = root / "bin" / "separate-sing-box"
            Path(binary).rename(moved)
            old_cfg = cfg.read_bytes()
            prov = cfg.parent / ".evergreen-provenance.json"
            old_prov = prov.read_bytes()
            result = remote_config.sync_isp(
                node, {"type": "socks", "server": "203.0.113.8", "server_port": 1080},
                runner=runner, verifier=lambda n: {"health": "proxy"}, cfg_path=str(cfg),
                bin_path=str(moved), master_secret=self.secret)
            self.assertFalse(result["ok"])
            self.assertTrue(result["rolled_back"])
            self.assertEqual(cfg.read_bytes(), old_cfg)
            self.assertEqual(prov.read_bytes(), old_prov)

    def test_tampered_backup_is_never_restored_or_restarted(self):
        with owned_target() as target:
            node, root, cfg, binary, env, runner, calls, initial = target
            self.assertTrue(remote_config.apply_config(node, initial, runner=runner, cfg_path=str(cfg),
                                                       bin_path=binary, master_secret=self.secret)[0])
            before_log = (root / "systemctl.log").read_bytes()
            Path(str(cfg) + ".ownline.bak").write_text("tampered")
            before = cfg.read_bytes()
            self.assertFalse(remote_config.rollback_config(node, runner=runner, cfg_path=str(cfg), bin_path=binary, master_secret=self.secret))
            self.assertEqual(cfg.read_bytes(), before)
            self.assertEqual((root / "systemctl.log").read_bytes(), before_log)

    def test_restart_failure_restores_original_config_and_provenance(self):
        with owned_target() as target:
            node, root, cfg, binary, env, runner, calls, initial = target
            prov = cfg.parent / ".evergreen-provenance.json"
            old_cfg, old_prov = cfg.read_bytes(), prov.read_bytes()
            env["RESTART_FAIL"] = "1"
            changed = json.loads(json.dumps(initial))
            changed["inbounds"][0]["listen_port"] = 8443
            self.assertFalse(remote_config.apply_config(node, changed, runner=runner, cfg_path=str(cfg),
                                                        bin_path=binary, master_secret=self.secret)[0])
            self.assertEqual(cfg.read_bytes(), old_cfg)
            self.assertEqual(prov.read_bytes(), old_prov)

    def test_master_secret_is_dedicated_stable_and_target_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                provenance.load_master_secret(tmp)
            key = provenance.load_master_secret(tmp, create=True)
            self.assertEqual(len(key), 32)
            Path(tmp, "settings.json").write_text(json.dumps({"sub_token": "rotated"}))
            self.assertEqual(provenance.load_master_secret(tmp, create=True), key)
            node_key = b"n" * 32
            self.assertEqual(provenance.secret_for_node({"control_secret": node_key.hex()}, tmp), node_key)
            self.assertEqual(provenance.secret_for_node({}, tmp), key)
            for invalid in ("", "shared-secret", "0" * 63, 123):
                with self.assertRaises(ValueError):
                    provenance.secret_for_node({"control_secret": invalid}, tmp)
            os.chmod(Path(tmp, "master_secret"), 0o644)
            with self.assertRaises(ValueError):
                provenance.load_master_secret(tmp)

    def test_unverified_target_cannot_be_adopted_by_manifest_injection(self):
        calls = []
        def missing(n, command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess([], 1, "", "missing")
        self.assertFalse(provenance.inject_remote_provenance({"host": "203.0.113.1"}, "{}", self.secret, missing))
        self.assertEqual(len(calls), 1)
        self.assertNotIn("mkdir", calls[0])
        self.assertNotIn("WriteAllBytes", calls[0])

    def test_hy2_certificate_helper_uses_rsa_2048(self):
        cert, key = remote_config.generate_self_signed_cert_pem("example.test")
        result = subprocess.run(["openssl", "pkey", "-text", "-noout"], input=key, text=True,
                                capture_output=True, check=True, timeout=10)
        self.assertIn("2048 bit", result.stdout)
        self.assertIn("BEGIN CERTIFICATE", cert)


if __name__ == "__main__":
    unittest.main()
