"""Offline uninstallation checks; all file removal occurs in disposable roots."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from nodekit import maintenance, provenance


def caddy_template():
    source = (ROOT / "deploy/install.sh").read_text()
    body = source.split('cat > "$CADDY_STAGED" << CADDYEOF\n', 1)[1].split('\nCADDYEOF', 1)[0]
    return (body.replace('$SETUP_JOB', 'offline').replace('$PASS_HASH', '$2b$14$' + 'a' * 53)
            .replace('${DOMAIN}', 'example.test').replace('$TLS_DIRECTIVE', '') + '\n')


class SafeUninstallTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for path in ('opt/web', 'opt/web-data', 'opt/sing-box', 'opt/ownline-upgrade',
                     'etc/sing-box', 'etc/caddy', 'etc/systemd/system', 'run', 'bin'):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        self.data = self.root / 'opt/web-data'
        self.cfg = self.root / 'opt/sing-box/config.json'
        self.cfg.write_text('{"inbounds":[]}')
        self.manifest = self.root / 'etc/sing-box/.evergreen-provenance.json'
        secret = provenance.load_master_secret(self.data, create=True)
        self.node = {'name': 'local node', 'host': '203.0.113.7', 'provenance_id': '203.0.113.7',
                     'source': 'builtin', 'local': True}
        self.manifest.write_text(json.dumps(provenance.sign_provenance(
            self.node['host'], provenance.compute_config_sha256(self.cfg.read_bytes()), secret)))
        (self.data / 'nodes.json').write_text(json.dumps([self.node]))
        (self.data / 'settings.json').write_text(json.dumps({'domain': 'example.test'}))
        self.caddy = self.root / 'etc/caddy/Caddyfile'
        self.caddy.write_text(caddy_template())
        self.units = self.root / 'etc/systemd/system'
        for name in maintenance.SERVICES:
            if name == 'caddy.service':
                raw = '[Service]\nExecStart=/usr/bin/caddy run --environ --config /etc/caddy/Caddyfile\n'
            elif name == 'ownline-upgrade-recovery.service':
                raw = '[Service]\nExecStart=/usr/bin/python3 /opt/ownline-upgrade/release.py --recover\n'
            elif name == 'ownline-upgrade-recovery.timer':
                raw = '[Timer]\nUnit=ownline-upgrade-recovery.service\n'
            else:
                raw = (ROOT / 'deploy/systemd' / name).read_text()
            (self.units / name).write_text(raw)
        (self.root / 'opt/ownline-upgrade/release.py').write_text('retained recovery')
        self.journal = self.root / 'opt/.web-upgrade-journal.json'
        self.journal.write_text('{}')
        self.log = self.root / 'systemctl.log'
        binary = self.root / 'bin'
        (binary / 'flock').write_text(
            '#!/usr/bin/env python3\nimport fcntl, subprocess, sys\n'
            "with open(sys.argv[4], 'a') as f:\n fcntl.flock(f, fcntl.LOCK_EX)\n"
            ' sys.exit(subprocess.run(sys.argv[5:]).returncode)\n')
        (binary / 'systemctl').write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$UNIT_LOG"\n'
            '[ "$1" != stop ] || [ "$2" != "$FAIL_STOP" ] || exit 1\n'
            'if [ "$1" = show ]; then\n'
            ' if [ "$2" = "$STILL_ACTIVE" ]; then echo active; else echo inactive; fi\nfi\nexit 0\n')
        for path in binary.iterdir():
            path.chmod(0o755)
        self.env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'],
                        UNIT_LOG=str(self.log), FAIL_STOP='', STILL_ACTIVE='')
        self.calls = []

    def runner(self, cmd, **kwargs):
        self.calls.append(cmd)
        return subprocess.run(cmd, env=self.env, **kwargs)

    def commands(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_missing_invalid_wrong_target_or_changed_config_never_issue_service_commands(self):
        original = self.manifest.read_bytes()
        old_cfg = self.cfg.read_bytes()
        for fault in ('missing', 'invalid', 'target', 'config', 'local-record'):
            with self.subTest(fault=fault):
                self.manifest.write_bytes(original)
                self.cfg.write_bytes(old_cfg)
                (self.data / 'nodes.json').write_text(json.dumps([self.node]))
                if fault == 'missing':
                    self.manifest.unlink()
                elif fault in ('invalid', 'target'):
                    manifest = json.loads(original)
                    manifest['signature' if fault == 'invalid' else 'node_id'] = 'wrong'
                    self.manifest.write_text(json.dumps(manifest))
                elif fault == 'config':
                    self.cfg.write_bytes(old_cfg + b' ')
                else:
                    (self.data / 'nodes.json').write_text(json.dumps([{**self.node, 'local': False}]))
                with self.assertRaises(PermissionError):
                    maintenance.uninstall(root=self.root, purge=True, runner=self.runner)
                self.assertEqual(self.commands(), [])
                self.assertTrue(self.journal.exists())
                self.assertTrue((self.units / 'sing-box.service').exists())

    def test_shared_caddy_foreign_units_or_overrides_fail_before_service_commands(self):
        initial = self.caddy.read_text()
        unit = self.units / 'admin.service'
        initial_unit = unit.read_text()
        for fault in ('shared-caddy', 'foreign-unit', 'override'):
            with self.subTest(fault=fault):
                self.caddy.write_text(initial)
                unit.write_text(initial_unit)
                if fault == 'shared-caddy':
                    self.caddy.write_text(initial + '\nother.test { respond 200 }\n')
                elif fault == 'foreign-unit':
                    unit.write_text('[Service]\nExecStart=/usr/bin/other-project\n')
                else:
                    (self.units / 'caddy.service.d').mkdir()
                with self.assertRaises(PermissionError):
                    maintenance.uninstall(root=self.root, runner=self.runner)
                self.assertEqual(self.commands(), [])

    def test_locked_metadata_drift_prevents_all_service_commands(self):
        def drift(cmd, **kwargs):
            if 'flock -x' in cmd[-1]:
                self.caddy.write_text(self.caddy.read_text() + '\n# changed after inspection\n')
            return self.runner(cmd, **kwargs)
        with self.assertRaises(RuntimeError):
            maintenance.uninstall(root=self.root, purge=True, runner=drift)
        self.assertEqual(self.commands(), [])
        self.assertTrue(self.journal.exists())

    def test_valid_uninstall_stops_recovery_first_then_disables_and_preserves_data(self):
        result = maintenance.uninstall(root=self.root, runner=self.runner)
        self.assertTrue(result['ok'])
        commands = self.commands()
        stopped = [line.split()[1] for line in commands if line.startswith('stop ')]
        self.assertEqual(stopped, list(maintenance.SERVICES))
        self.assertEqual(stopped[:2], ['ownline-upgrade-recovery.timer', 'ownline-upgrade-recovery.service'])
        self.assertLess(max(i for i, line in enumerate(commands) if line.startswith('stop ')),
                        min(i for i, line in enumerate(commands) if line.startswith('disable ')))
        self.assertTrue(self.data.exists())
        self.assertTrue(self.manifest.exists())
        self.assertTrue(self.journal.exists())
        self.assertTrue((self.root / 'opt/ownline-upgrade').exists())
        self.assertFalse(any(self.units.iterdir()))

    def test_purge_removes_recovery_and_journal_only_after_stopped(self):
        self.assertTrue(maintenance.uninstall(root=self.root, purge=True, runner=self.runner)['ok'])
        self.assertIn('stop ownline-upgrade-recovery.service', self.commands())
        for path in ('opt/web', 'opt/web-data', 'opt/sing-box', 'opt/ownline-upgrade',
                     'opt/.web-upgrade-journal.json', 'etc/caddy/Caddyfile'):
            self.assertFalse((self.root / path).exists(), path)

    def test_failed_or_unconfirmed_recovery_stop_never_disables_or_purges(self):
        for variable in ('FAIL_STOP', 'STILL_ACTIVE'):
            with self.subTest(variable=variable):
                self.env[variable] = 'ownline-upgrade-recovery.service'
                with self.assertRaises(RuntimeError):
                    maintenance.uninstall(root=self.root, purge=True, runner=self.runner)
                self.assertFalse(any(line.startswith('disable ') for line in self.commands()))
                self.assertTrue(self.journal.exists())
                self.assertTrue((self.root / 'opt/ownline-upgrade/release.py').exists())
                self.assertTrue((self.units / 'ownline-upgrade-recovery.service').exists())
                self.env[variable] = ''

    def test_dry_run_proves_ownership_without_stopping_or_deleting(self):
        result = maintenance.uninstall(root=self.root, purge=True, dry_run=True, runner=self.runner)
        self.assertTrue(result['dry_run'])
        self.assertEqual(self.commands(), [])
        self.assertTrue(self.journal.exists())
        self.assertTrue((self.units / 'sing-box.service').exists())

    def test_direct_helper_loads_in_source_and_flat_runtime_layouts(self):
        source = ROOT / 'server/nodekit/maintenance.py'
        subprocess.run([sys.executable, str(source), '--help'], check=True, capture_output=True)
        flat = self.root / 'flat'
        (flat / 'nodekit').mkdir(parents=True)
        for name in ('__init__.py', 'maintenance.py', 'provenance.py'):
            shutil.copy2(ROOT / 'server/nodekit' / name, flat / 'nodekit' / name)
        subprocess.run([sys.executable, str(flat / 'nodekit/maintenance.py'), '--help'], check=True, capture_output=True)

    def test_shell_uninstall_delegates_all_mutations_to_verifier(self):
        source = (ROOT / 'deploy/install.sh').read_text()
        block = source.split('# ---------- 卸载逻辑 ----------', 1)[1].split('# FIRST INSTALL CONFLICT CHECK BEGIN', 1)[0]
        self.assertIn('nodekit/maintenance.py', block)
        self.assertIn('--uninstall', block)
        self.assertNotIn('systemctl ', block)
        self.assertNotIn('rm -', block)


if __name__ == '__main__':
    unittest.main()
