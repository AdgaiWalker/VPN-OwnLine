"""Offline release-interface regressions with injected transport and host adapters."""
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy"))
import release as deployment_release
import runtime_manifest


class UpgradeScriptTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.web = self.root / "web"
        self.create_source("v0.5.0", "old")
        runtime_manifest.install_runtime(self.source, self.web)
        (self.web / "runtime.conf").write_text("keep runtime configuration")
        (self.web / "assets").mkdir()
        (self.web / "assets/custom.svg").write_text("keep custom asset")
        (self.root / "web-data").mkdir()
        (self.root / "web-data/settings.json").write_text("keep settings")
        (self.root / "Caddyfile").write_text("keep Caddy configuration")
        self.create_source("v0.6.1", "new")
        self.archive = self.root / "release.tar.gz"
        with tarfile.open(self.archive, "w:gz") as bundle:
            bundle.add(self.source, arcname="release")
        self.release_id = hashlib.sha256(self.archive.read_bytes()).hexdigest()
        self.restart = Mock()
        self.probe = Mock(return_value=True)

    def create_source(self, version, marker):
        files = {
            "server/admin.py": "marker = " + repr(marker) + "\n",
            "server/addnode.sh": "#!/bin/bash\ntrue\n",
            "server/nodekit/__init__.py": "",
            "server/nodekit/system_updater.py": "CURRENT_VERSION = " + repr(version) + "\n",
            "web/index.html": marker,
            "web/change-password.html": "password page",
            "web/backup-crypto.js": "",
            "requirements.lock": "# offline fixture\n",
        }
        for name, content in files.items():
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        for name in ("install.sh", "upgrade.sh", "runtime_manifest.py", "release.py"):
            path = self.source / "deploy" / name
            path.parent.mkdir(exist_ok=True)
            shutil.copy2(ROOT / "deploy" / name, path)

    def fetch(self, target, destination):
        shutil.copyfile(self.archive, destination)
        return self.release_id

    def upgrade(self, **overrides):
        arguments = dict(fetch=self.fetch, restart=self.restart, probe=self.probe)
        arguments.update(overrides)
        return deployment_release.upgrade_release("v0.6.1", self.web, **arguments)

    def tree(self):
        return {str(path.relative_to(self.web)): path.read_bytes()
                for path in self.web.rglob("*") if path.is_file()}

    def test_success_replaces_complete_runtime_and_preserves_runtime_assets(self):
        result = self.upgrade()
        self.assertIn("new", (self.web / "admin.py").read_text())
        self.assertEqual(result, {"version": "v0.6.1", "release_id": self.release_id})
        self.assertEqual((self.web / "runtime.conf").read_text(), "keep runtime configuration")
        self.assertEqual((self.web / "assets/custom.svg").read_text(), "keep custom asset")
        self.assertEqual((self.root / "web-data/settings.json").read_text(), "keep settings")
        self.assertEqual((self.root / "Caddyfile").read_text(), "keep Caddy configuration")
        self.probe.assert_called_once_with(result)
        self.restart.assert_called_once()

    def test_copy_failure_at_multiple_stages_leaves_active_runtime_untouched(self):
        original = shutil.copy2
        for failed_name in ("admin.py", "index.html", "runtime_manifest.py"):
            with self.subTest(failed_name=failed_name):
                before = self.tree()
                def failing_copy(source, target, *args, **kwargs):
                    result = original(source, target, *args, **kwargs)
                    if "candidate" in Path(target).parts and Path(target).name == failed_name:
                        raise OSError("simulated disk full")
                    return result
                with patch.object(runtime_manifest.shutil, "copy2", side_effect=failing_copy):
                    with self.assertRaises(OSError):
                        self.upgrade()
                self.assertEqual(self.tree(), before)
                self.restart.assert_not_called()

    def test_failed_atomic_exchange_leaves_active_runtime_in_place(self):
        before = self.tree()
        with self.assertRaises(OSError):
            self.upgrade(exchange=Mock(side_effect=OSError("exchange unsupported")))
        self.assertEqual(self.tree(), before)
        self.restart.assert_not_called()
        self.probe.assert_not_called()
        self.assertFalse(deployment_release._journal_path(self.web).exists())

    def test_restart_and_version_failures_both_restore_original_runtime(self):
        for failure in ("restart", "version"):
            with self.subTest(failure=failure):
                before = self.tree()
                restart = Mock(side_effect=[RuntimeError("restart failed"), None] if failure == "restart" else None)
                probe = Mock(side_effect=[False, True] if failure == "version" else [True])
                with self.assertRaisesRegex(RuntimeError, "restored and verified"):
                    self.upgrade(restart=restart, probe=probe)
                self.assertEqual(self.tree(), before)
                self.assertEqual(restart.call_count, 2)
                self.assertEqual(probe.call_args.args[0]["version"], "v0.5.0")

    def test_failed_rollback_probe_is_reported_without_claiming_recovery(self):
        self.probe.return_value = False
        with self.assertRaisesRegex(RuntimeError, "rollback requires attention"):
            self.upgrade()
        self.assertIn("old", (self.web / "admin.py").read_text())

    def test_official_failure_does_not_accept_available_malicious_mirror(self):
        before = self.tree()
        calls = []
        def opener(request, **kwargs):
            calls.append(request.full_url)
            if request.full_url.startswith("https://codeload.github.com/"):
                raise OSError("official unavailable")
            return io.BytesIO(b"malicious mirror payload")
        def fetch(target, destination):
            return deployment_release.download_official(target, destination, opener=opener)
        with self.assertRaises(OSError):
            self.upgrade(fetch=fetch)
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith("https://codeload.github.com/"))
        self.assertEqual(self.tree(), before)
        self.restart.assert_not_called()

    def test_requested_tag_mismatch_never_switches_active_runtime(self):
        before = self.tree()
        with self.assertRaisesRegex(ValueError, "requested tag"):
            deployment_release.upgrade_release("v9.9.9", self.web, fetch=self.fetch,
                                              restart=self.restart, probe=self.probe)
        self.assertEqual(self.tree(), before)
        self.restart.assert_not_called()

    def test_redirect_to_mirror_is_rejected_before_reading_bytes(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = "https://mirror.example.com/release.tar.gz"
        output = self.root / "untrusted.tar.gz"
        with self.assertRaisesRegex(ValueError, "official HTTPS"):
            deployment_release.download_official("v0.6.1", output, opener=Mock(return_value=response))
        response.read.assert_not_called()
        self.assertFalse(output.exists())

    def test_unsafe_archive_never_changes_active_files(self):
        before = self.tree()
        for name, kind in (("release/../../escaped", tarfile.REGTYPE), ("release/link", tarfile.SYMTYPE)):
            with self.subTest(name=name):
                with tarfile.open(self.archive, "w:gz") as bundle:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = "/etc"
                    bundle.addfile(member)
                with self.assertRaises(ValueError):
                    self.upgrade()
                self.assertEqual(self.tree(), before)
                self.assertFalse((self.root / "escaped").exists())

    def test_runtime_symlink_is_not_followed_during_overlay(self):
        outside = self.root / "outside.py"
        outside.write_text("must remain unchanged")
        (self.web / "admin.py").unlink()
        (self.web / "admin.py").symlink_to(outside)
        (self.web / ".release.json").symlink_to(outside)
        self.upgrade()
        self.assertEqual(outside.read_text(), "must remain unchanged")
        self.assertFalse((self.web / "admin.py").is_symlink())

    def test_first_install_layout_can_find_and_start_upgrade(self):
        installed = self.root / "first-install"
        runtime_manifest.install_runtime(ROOT, installed)
        for resource in ("upgrade.sh", "release.py", "runtime_manifest.py"):
            self.assertTrue((installed / "deploy" / resource).is_file())
        self.assertTrue(os.access(installed / "deploy/upgrade.sh", os.X_OK))
        namespace = runpy.run_path(str(installed / "nodekit/system_updater.py"))
        runner = Mock(return_value="started")
        result = namespace["trigger_upgrade"]("v0.6.1", runner=runner)
        self.assertTrue(result["ok"])
        runner.assert_called_once_with(str((installed / "deploy/upgrade.sh").resolve()), "v0.6.1")

    def test_running_release_identity_is_frozen_before_disk_switch(self):
        installed = self.root / "running-install"
        runtime_manifest.install_runtime(ROOT, installed)
        marker = installed / ".release.json"
        marker.write_text(json.dumps({"release_id": "a" * 64}))
        namespace = runpy.run_path(str(installed / "nodekit/system_updater.py"))
        marker.write_text(json.dumps({"release_id": "b" * 64}))
        self.assertEqual(namespace["get_version_info"]()["release_id"], "a" * 64)

    def test_version_probe_rejects_same_version_from_old_release(self):
        expected = {"version": "v0.6.1", "release_id": "a" * 64}
        for release_id, accepted in (("b" * 64, False), ("a" * 64, True)):
            with self.subTest(release_id=release_id):
                response = Mock()
                response.__enter__ = Mock(return_value=response)
                response.__exit__ = Mock(return_value=False)
                response.read.return_value = json.dumps({"ok": True, "version": "v0.6.1", "release_id": release_id}).encode()
                with patch.object(deployment_release.urllib.request, "urlopen", return_value=response), patch.object(deployment_release.time, "sleep"):
                    self.assertEqual(deployment_release.probe_runtime(expected, attempts=1), accepted)

    def test_final_job_status_records_success_and_failure(self):
        for succeeded in (True, False):
            with self.subTest(succeeded=succeeded):
                fields = {"version": "v0.6.1", "release_id": self.release_id}
                result = Mock(return_value=fields) if succeeded else Mock(side_effect=RuntimeError("restored and verified"))
                directory = self.root / "status"
                with patch.dict(os.environ, OWNLINE_UPGRADE_JOB_ID="a" * 32, OWNLINE_UPGRADE_STATUS_DIR=str(directory)), patch.object(sys, "argv", ["release.py", "v0.6.1"]), patch.object(os, "geteuid", return_value=0), patch.object(deployment_release, "upgrade_release", result):
                    self.assertEqual(deployment_release.main(), 0 if succeeded else 1)
                status = json.loads((directory / ("a" * 32 + ".json")).read_text())
                self.assertEqual(status["status"], "succeeded" if succeeded else "failed")
                self.assertEqual((directory / ("a" * 32 + ".json")).stat().st_mode & 0o777, 0o600)

    def test_sigkill_before_and_after_atomic_exchange_recovers_with_active_present(self):
        if sys.platform not in ("darwin", "linux"):
            self.skipTest("host does not offer the supported atomic exchange Adapter")
        for moment in ("before", "after", "before_commit", "committed"):
            with self.subTest(moment=moment):
                code = r"""
import hashlib, os, shutil, signal, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import release
web, archive, moment = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
def fetch(target, destination):
    shutil.copyfile(archive, destination)
    return hashlib.sha256(archive.read_bytes()).hexdigest()
def exchange(left, right):
    if moment == 'before': os.kill(os.getpid(), signal.SIGKILL)
    release.atomic_exchange(left, right)
    if moment == 'after': os.kill(os.getpid(), signal.SIGKILL)
def probe(expected):
    if moment == 'before_commit': os.kill(os.getpid(), signal.SIGKILL)
    return True
original = release._atomic_json
def journal(path, value):
    original(path, value)
    if moment == 'committed' and value.get('phase') == 'committed':
        os.kill(os.getpid(), signal.SIGKILL)
release._atomic_json = journal
release.upgrade_release('v0.6.1', web, fetch=fetch, restart=lambda: None, probe=probe, exchange=exchange)
"""
                result = subprocess.run([sys.executable, "-c", code, str(ROOT / "deploy"),
                                         str(self.web), str(self.archive), moment],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, -signal.SIGKILL, result.stderr)
                self.assertTrue((self.web / "admin.py").is_file())
                journal = deployment_release._journal_path(self.web)
                self.assertTrue(journal.is_file())
                self.assertEqual(journal.stat().st_mode & 0o777, 0o600)
                restart, probe = Mock(), Mock(return_value=True)
                deployment_release.recover_release(self.web, restart=restart, probe=probe)
                self.assertFalse(journal.exists())
                marker = "new" if moment == "committed" else "old"
                self.assertIn(marker, (self.web / "admin.py").read_text())
                self.assertEqual(restart.call_count, int(moment in ("after", "before_commit")))
                if moment == "committed":
                    # Restore the fixture for the remaining assertions and cleanups.
                    self.assertEqual(json.loads((self.web / ".release.json").read_text())["release_id"], self.release_id)

    def test_unsupported_platform_fails_before_changing_active_runtime(self):
        before = self.tree()
        with patch.object(deployment_release.sys, "platform", "unsupported-os"):
            with self.assertRaises(OSError):
                self.upgrade()
        self.assertEqual(self.tree(), before)
        self.restart.assert_not_called()

    def test_default_production_restart_requires_ownership_before_exchange(self):
        before = self.tree()
        exchange = Mock()
        with patch.object(deployment_release, "authorize_restart", side_effect=PermissionError("missing ownership")), patch.object(deployment_release, "restart_admin") as restart:
            with self.assertRaises(PermissionError):
                deployment_release.upgrade_release("v0.6.1", self.web, fetch=self.fetch,
                                                  probe=self.probe, exchange=exchange)
        exchange.assert_not_called()
        restart.assert_not_called()
        self.assertEqual(self.tree(), before)

    def test_restart_ownership_checks_signature_identity_and_actual_config(self):
        sys.path.insert(0, str(ROOT / "server"))
        from nodekit import provenance
        data, config, manifest = self.root / "ownership-data", self.root / "proxy.json", self.root / "ownership.json"
        data.mkdir()
        key = b"a" * 32
        (data / "master_secret").write_text(key.hex())
        (data / "master_secret").chmod(0o600)
        original = b'{"inbounds": []}\n'
        config.write_bytes(original)
        (data / "nodes.json").write_text(json.dumps([{"local": True, "host": "8.8.8.8", "provenance_id": "stable-node"}]))
        valid = provenance.sign_provenance("stable-node", provenance.compute_config_sha256(original), key)
        manifest.write_text(json.dumps(valid))
        arguments = dict(data_dir=data, cfg_path=config, manifest_path=manifest, provenance_module=provenance)
        deployment_release.authorize_restart(**arguments)
        for fault in ("signature", "target", "config", "missing_key"):
            with self.subTest(fault=fault):
                manifest.write_text(json.dumps(valid))
                config.write_bytes(original)
                (data / "master_secret").write_text(key.hex())
                if fault == "signature":
                    manifest.write_text(json.dumps(dict(valid, signature="forged")))
                elif fault == "target":
                    manifest.write_text(json.dumps(provenance.sign_provenance("other-node", provenance.compute_config_sha256(original), key)))
                elif fault == "config":
                    config.write_bytes(original + b" ")
                else:
                    (data / "master_secret").unlink()
                with self.assertRaises(PermissionError):
                    deployment_release.authorize_restart(**arguments)
        # The production restart function calls the gate before systemctl.
        gate = deployment_release.authorize_restart
        with patch.object(deployment_release, "authorize_restart", side_effect=lambda: gate(**arguments)), patch.object(deployment_release.subprocess, "run") as command:
            with self.assertRaises(PermissionError):
                deployment_release.restart_admin()
        command.assert_not_called()

    def test_stable_recovery_tools_include_frozen_ownership_verifier_and_timer(self):
        stable, units, runner = self.root / "stable-tools", self.root / "units", Mock()
        helper = deployment_release.install_recovery_runtime(stable, units, runner)
        self.assertEqual(helper, stable / "release.py")
        verifier = stable / "upgrade_provenance.py"
        self.assertTrue(verifier.is_file())
        self.assertEqual(verifier.read_bytes(), (ROOT / "server/nodekit/provenance.py").read_bytes())
        self.assertEqual(stable.stat().st_mode & 0o777, 0o700)
        self.assertIn(str(helper) + " --recover", (units / "ownline-upgrade-recovery.service").read_text())
        self.assertIn("OnUnitActiveSec=20s", (units / "ownline-upgrade-recovery.timer").read_text())
        with patch.object(deployment_release, "__file__", str(helper)):
            self.assertEqual(Path(deployment_release._provenance_module().__file__), verifier.resolve())
        self.assertEqual(runner.call_count, 3)

    def test_sync_host_config_converges_legacy_units_caddyfile_respects_quota_and_rolls_back(self):
        units = self.root / "host-units"
        units.mkdir()
        sb_dir = self.root / "host-singbox"
        sb_dir.mkdir()
        (sb_dir / "config.json").write_text('{"inbounds":[]}\n', encoding="utf-8")
        sb_log = self.root / "sing-box.log"
        quota_flag = self.root / "quota-paused"
        caddy_lib = self.root / "var-caddy"

        # Legacy units lacking hardening and ConditionPathExists=!/var/lib/ownline/quota-paused
        (units / "admin.service").write_text("[Service]\nExecStart=/usr/bin/python3 /opt/web/admin.py\n", encoding="utf-8")
        (units / "caddy.service").write_text("[Service]\nUser=root\n", encoding="utf-8")
        (units / "sing-box.service").write_text("[Service]\nUser=root\nExecStart=/opt/sing-box/sing-box run\n", encoding="utf-8")

        legacy_hash = "$2b$14$" + "c" * 53
        legacy_caddy = (
            "# ownline-setup-job:legacy1\n"
            "(app) {\n"
            "\tredir /p / 308\n"
            "\tredir /p/* / 308\n"
            "\thandle /s/* {\n\t\treverse_proxy 127.0.0.1:8099\n\t}\n"
            "\thandle /join/* {\n\t\treverse_proxy 127.0.0.1:8099\n\t}\n"
            "\t@blocked path /sub*\n"
            "\thandle @blocked {\n\t\trespond 404\n\t}\n"
            "\thandle_path /api/* {\n\t\tbasic_auth {\n\t\t\tadmin " + legacy_hash + "\n\t\t}\n\t\treverse_proxy 127.0.0.1:8099\n\t}\n"
            "\t@sensitive path /tc.json /nodes.json /retired-nodes-*.json\n"
            "\thandle @sensitive {\n\t\trespond 404\n\t}\n"
            "\t@pubjson path /status.json /servers.json /usage.json /quota.json\n"
            "\thandle @pubjson {\n\t\tbasic_auth {\n\t\t\tadmin " + legacy_hash + "\n\t\t}\n\t\theader Cache-Control \"no-store\"\n\t\troot * /opt/web-data\n\t\tfile_server\n\t}\n"
            "\thandle {\n\t\tbasic_auth {\n\t\t\tadmin " + legacy_hash + "\n\t\t}\n\t\theader Cache-Control \"no-store\"\n\t\troot * /opt/web\n\t\tfile_server\n\t}\n"
            "}\n\n"
            ":80 {\n\tredir https://legacy.test:8443{uri} 308\n}\n\n"
            "https://legacy.test:8443 {\n\ttls internal\n\timport app\n}\n"
        )
        caddyfile = self.root / "host-Caddyfile"
        caddyfile.write_text(legacy_caddy, encoding="utf-8")

        cmds = []
        def ok_runner(cmd, **kwargs):
            cmds.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        # 1. Quota-paused flag prevents sing-box start/restart on upgrade
        quota_flag.write_text("paused\n", encoding="utf-8")
        res = deployment_release.sync_host_config(
            ROOT,
            unit_dir=units,
            caddyfile=caddyfile,
            singbox_dir=sb_dir,
            singbox_log=sb_log,
            quota_pause_flag=quota_flag,
            caddy_lib_dir=caddy_lib,
            runner=ok_runner,
            caddy_bin="/usr/local/bin/caddy",
            ensure_accounts=False,
        )
        self.assertTrue(res["changed"])
        self.assertTrue(res["caddyfile_updated"])
        self.assertEqual(res["units_updated"], ["admin.service", "caddy.service", "sing-box.service"])
        self.assertIn("ConditionPathExists=!/var/lib/ownline/quota-paused", (units / "sing-box.service").read_text(encoding="utf-8"))
        self.assertNotIn(":80 {", caddyfile.read_text(encoding="utf-8"))
        self.assertIn(["systemctl", "stop", "sing-box"], cmds)
        self.assertNotIn(["systemctl", "restart", "sing-box"], cmds)

        # 2. Second run is completely idempotent (no restarts)
        cmds.clear()
        res2 = deployment_release.sync_host_config(
            ROOT,
            unit_dir=units,
            caddyfile=caddyfile,
            singbox_dir=sb_dir,
            singbox_log=sb_log,
            quota_pause_flag=quota_flag,
            caddy_lib_dir=caddy_lib,
            runner=ok_runner,
            caddy_bin="/usr/local/bin/caddy",
            ensure_accounts=False,
        )
        self.assertFalse(res2["changed"])
        self.assertEqual(cmds, [])

        # 3. Custom Caddyfile is skipped safely; failure rolls back units atomically
        caddyfile.write_text("custom.example.com {\n  respond 200\n}\n", encoding="utf-8")
        old_sb = "[Service]\nUser=root\n"
        (units / "sing-box.service").write_text(old_sb, encoding="utf-8")
        def fail_on_restart(cmd, **kwargs):
            if cmd == ["systemctl", "stop", "sing-box"]:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if cmd == ["systemctl", "restart", "caddy"]:
                raise subprocess.CalledProcessError(1, cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        # Force caddy.service drift to trigger restart caddy failure and verify rollback
        old_cd = "[Service]\nUser=old\n"
        (units / "caddy.service").write_text(old_cd, encoding="utf-8")
        with self.assertRaises(subprocess.CalledProcessError):
            deployment_release.sync_host_config(
                ROOT,
                unit_dir=units,
                caddyfile=caddyfile,
                singbox_dir=sb_dir,
                singbox_log=sb_log,
                quota_pause_flag=quota_flag,
                caddy_lib_dir=caddy_lib,
                runner=fail_on_restart,
                caddy_bin="/usr/local/bin/caddy",
                ensure_accounts=False,
            )
        self.assertEqual((units / "sing-box.service").read_text(encoding="utf-8"), old_sb)
        self.assertEqual((units / "caddy.service").read_text(encoding="utf-8"), old_cd)
        self.assertEqual(caddyfile.read_text(encoding="utf-8"), "custom.example.com {\n  respond 200\n}\n")

    def test_upgrade_release_rolls_back_host_sync_when_probe_fails(self):
        host_rolled_back = []
        def fake_sync(active_dir):
            return {"changed": True, "rollback": lambda: host_rolled_back.append(str(active_dir))}
        with self.assertRaisesRegex(RuntimeError, "previous runtime restored"):
            self.upgrade(probe=Mock(side_effect=[False, True]), sync_host=fake_sync)
        self.assertEqual(len(host_rolled_back), 1)
