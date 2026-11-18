"""The root-only data directory is read by admin, never by Caddy's user."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import admin


class StatusDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.data.chmod(0o700)
        for name in ('status', 'servers', 'usage', 'quota'):
            (self.data / (name + '.json')).write_text(json.dumps({'fixture': name}))
        for target, value in (('DATA', str(self.data)), ('INITIAL_PASSWORD_MARKER', self.data / 'gate')):
            p = patch.object(admin, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), admin.H)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        c.request('GET', path)
        r = c.getresponse()
        result = r.status, dict(r.getheaders()), json.loads(r.read())
        c.close()
        return result

    def test_private_directory_snapshot_survives_repeated_reads_and_both_prefixes(self):
        for prefix in ('', '/api'):
            for name in ('status', 'servers', 'usage', 'quota'):
                for _ in range(2):
                    code, headers, body = self.get(prefix + '/' + name + '.json')
                    self.assertEqual(code, 200)
                    self.assertEqual(body, {'fixture': name})
                    self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.data.stat().st_mode & 0o777, 0o700)

    def test_missing_or_broken_snapshot_is_explicit_and_first_password_gate_remains(self):
        (self.data / 'status.json').unlink()
        self.assertEqual(self.get('/status.json')[0], 404)
        (self.data / 'status.json').write_text('{broken')
        self.assertEqual(self.get('/status.json')[0], 503)
        (self.data / 'gate').touch()
        self.assertEqual(self.get('/status.json')[0], 403)

    def test_gateway_proxies_allowlisted_snapshots_without_relaxing_private_permissions(self):
        script = (Path(__file__).resolve().parents[1] / 'deploy/install.sh').read_text()
        block = script.split('handle @pubjson {', 1)[1].split('\n\thandle {', 1)[0]
        self.assertIn('reverse_proxy 127.0.0.1:8099', block)
        self.assertIn('basic_auth', block)
        self.assertIn('forward_auth', block)
        self.assertNotIn('file_server', block)
        self.assertIn('chmod 700 /opt/web-data', script)


if __name__ == '__main__':
    unittest.main()
