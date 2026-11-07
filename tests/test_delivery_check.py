"""Exercise the installer's delivery checks with fake curl and DNS; no network."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / 'deploy/install.sh').read_text(encoding='utf-8')
FUNCTIONS = SCRIPT.split('# DELIVERY VERIFICATION FUNCTIONS BEGIN', 1)[1].split('# DELIVERY VERIFICATION FUNCTIONS END', 1)[0]
CONFLICT_CHECK = SCRIPT.split('# FIRST INSTALL CONFLICT CHECK BEGIN', 1)[1].split('# FIRST INSTALL CONFLICT CHECK END', 1)[0]


class DeliveryCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.args = self.directory / 'args'
        curl = self.directory / 'curl'
        curl.write_text('#!/bin/bash\nprintf "%s\\n" "$*" > "$TEST_ARGS"\ncat >/dev/null\nprintf "%s" "$TEST_STATUS"\nexit "$TEST_EXIT"\n')
        curl.chmod(0o755)
        dns = self.directory / 'getent'
        dns.write_text('#!/bin/bash\nprintf "%s STREAM host\\n" "$TEST_IP"\n')
        dns.chmod(0o755)
        systemctl = self.directory / 'systemctl'
        systemctl.write_text('#!/bin/bash\n[ "${3:-}" = "${TEST_ACTIVE_SERVICE:-}" ] && [ -n "${TEST_ACTIVE_SERVICE:-}" ]\n')
        systemctl.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(self.directory) + ':' + os.environ['PATH'],
                    'TEST_ARGS': str(self.args), 'TEST_STATUS': '200', 'TEST_EXIT': '0',
                    'TEST_IP': '198.51.100.1'}

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, command):
        return subprocess.run(['bash', '-c', 'set -euo pipefail\n' + FUNCTIONS + '\n' + command],
                              env=self.env, capture_output=True, text=True)

    def test_http_status_secret_is_not_in_process_arguments(self):
        result = self.execute('delivery_http_status "http://127.0.0.1:8099/s/secret-token"')
        self.assertEqual((result.returncode, result.stdout), (0, '200'))
        args = self.args.read_text()
        self.assertNotIn('secret-token', args)
        self.assertNotIn('-k', args.split())
        self.assertIn('--config -', args)

    def test_tls_failure_is_not_reported_as_status(self):
        self.env.update(TEST_STATUS='000', TEST_EXIT='60')
        result = self.execute('delivery_http_status "https://example.test:8443/" "example.test:8443:198.51.100.1"')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('--resolve example.test:8443:198.51.100.1', self.args.read_text())

    def test_dns_match_and_http_401_are_checked_separately(self):
        self.env['TEST_STATUS'] = '401'
        result = self.execute('delivery_dns_matches example.test 198.51.100.1 && '
                              '[ "$(delivery_http_status https://example.test:8443/ example.test:8443:198.51.100.1)" = 401 ]')
        self.assertEqual(result.returncode, 0)
        mismatch = self.execute('delivery_dns_matches example.test 198.51.100.2')
        self.assertNotEqual(mismatch.returncode, 0)
        self.env['TEST_STATUS'] = '404'
        unexpected = self.execute('[ "$(delivery_http_status https://example.test:8443/ example.test:8443:198.51.100.1)" = 401 ]')
        self.assertNotEqual(unexpected.returncode, 0)

    def test_standalone_install_detects_existing_config_and_running_service(self):
        cmd = 'set -euo pipefail\n' + CONFLICT_CHECK + '\ninstallation_conflict "$TEST_ROOT"'
        root = self.directory / 'root'
        root.mkdir()
        self.env['TEST_ROOT'] = str(root)
        blank = subprocess.run(['bash', '-c', cmd], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(blank.returncode, 0)
        existing = root / 'etc/caddy/Caddyfile'
        existing.parent.mkdir(parents=True)
        existing.write_text('existing application')
        conflict = subprocess.run(['bash', '-c', cmd], env=self.env, capture_output=True, text=True)
        self.assertEqual(conflict.returncode, 0)
        self.assertIn('/etc/caddy/Caddyfile', conflict.stdout)
        existing.unlink()
        self.env['TEST_ACTIVE_SERVICE'] = 'sing-box'
        running = subprocess.run(['bash', '-c', cmd], env=self.env, capture_output=True, text=True)
        self.assertEqual(running.returncode, 0)
        self.assertIn('sing-box', running.stdout)


if __name__ == '__main__':
    unittest.main()
